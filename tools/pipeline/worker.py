# Claude Worker daemon & Outbound Worker for Synora Agent Bridge
import base64
import json
import os
import logging
import ssl
import threading
import time
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519

from .bridge import Bridge
from .budget import BudgetExceeded, WorkerBudget
from .metadata import validate_job_payload
from .transport import certificate_options, normalize_gateway_url, websocket_url
from .protocol import (
    MSG_HEARTBEAT,
    MSG_JOB_ACK,
    MSG_JOB_ASSIGN,
    MSG_JOB_FAILURE,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_WORKER_REGISTER,
    MSG_WORKER_CHALLENGE,
    MSG_WORKER_AUTH,
)
from .result_envelope import ResultEnvelope, attest_result

logger = logging.getLogger(__name__)

import re

from .audit import redact_secret_values

def _redact_deep(value, depth=0):
    if depth > 20:
        return '[REDACTED_DEPTH_LIMIT]'
    if isinstance(value, str):
        return redact_secret_values(value)
    if isinstance(value, dict):
        return {_redact_deep(k, depth + 1): _redact_deep(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_deep(v, depth + 1) for v in value]
    return value


def sanitize_worker_result(result_dict: dict) -> dict:
    if not isinstance(result_dict, dict):
        return result_dict
    return _redact_deep(result_dict)



class WorkerConnectionError(ConnectionError):
    pass


class ResultNotDelivered(WorkerConnectionError):
    """The job finished but the connection failed before the Gateway acknowledged its result."""


class ClaudeWorker:
    def __init__(
        self,
        worker_id: str,
        bridge: Optional[Bridge] = None,
        gateway: Any = None,
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
        budget: Optional[WorkerBudget] = None,
    ):
        self.worker_id = worker_id
        self.bridge = bridge
        self.gateway = gateway
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self.capabilities = {'supported_tasks': ['docs', 'code', 'review']}
        if budget is None and bridge is not None:
            budget = WorkerBudget(bridge.records_dir.parent)
        self.budget = budget

    def _intake(self, job_data):
        """Check a Gateway job before any work. Remote fields never change the Worker's limits."""
        checked = validate_job_payload(job_data)
        if self.bridge is not None and checked['base_commit']:
            self.bridge.resolve_base(checked['base_commit'])
        if self.bridge is not None and self.budget is not None:
            self.budget.admit()

    def _release(self):
        if self.bridge is not None and self.budget is not None:
            self.budget.finish()

    def process_one_job(self) -> Optional[dict]:
        if not self.gateway:
            return None
        job_data = self.gateway.worker_poll_job(self.worker_id)
        if not job_data:
            return None

        job_id = job_data['job_id']
        developer_id = job_data['developer_id']
        task = job_data['task']
        task_type = job_data.get('task_type', 'docs')

        try:
            self._intake(job_data)
        except (ValueError, BudgetExceeded) as err:
            self.gateway.worker_submit_failure(self.worker_id, job_id, redact_secret_values(f'Refused: {err}'))
            return None

        try:
            if not self.bridge:
                result = {
                    'status': 'SUCCEEDED',
                    'output': f'Simulated bridge execution for job {job_id}',
                    'task': task,
                }
            else:
                record = self.bridge.create(
                    task=task,
                    task_type=task_type,
                    developer_id=developer_id,
                    branch=job_data.get('branch'),
                    base_commit=job_data.get('base_commit'),
                )
                local_job_id = record['job_id']
                self.bridge.execute(local_job_id)
                result = self.bridge.get(local_job_id)

            status = result.get('status', 'SUCCEEDED')
            result = sanitize_worker_result(result)
            result = attest_result(self.private_key, job_id, developer_id, self.worker_id, status, result)
            if hasattr(self.gateway, 'worker_submit_signed_result'):
                envelope = ResultEnvelope.create(
                    private_key=self.private_key,
                    job_id=job_id,
                    developer_id=developer_id,
                    worker_id=self.worker_id,
                    status=status,
                    result=result,
                )
                self.gateway.worker_submit_signed_result(envelope)
            else:
                self.gateway.worker_submit_result(self.worker_id, job_id, result)
            return result
        except Exception as err:
            self.gateway.worker_submit_failure(self.worker_id, job_id, redact_secret_values(f'{type(err).__name__}: {err}'))
            raise
        finally:
            self._release()


class LeadNotConfigured(RuntimeError):
    """A Lead job reached a Worker that has no Lead configured. The job is refused."""


class OutboundWorker(ClaudeWorker):
    """Outbound persistent Claude Worker client.

    Establishes strictly outbound connections to the Public Gateway (via WebSocket).
    Opens ZERO listening ports on Johan's computer.
    """

    def __init__(
        self,
        worker_id: str,
        gateway_url: Optional[str] = None,
        bridge: Optional[Bridge] = None,
        gateway: Any = None,
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
        heartbeat_interval: float = 10.0,
        max_backoff: float = 30.0,
        ssl_context: Optional[ssl.SSLContext] = None,
        poll_interval: float = 3.0,
        allow_insecure_lan: bool = False,
        budget: Optional[WorkerBudget] = None,
        lead: Any = None,
    ):
        super().__init__(worker_id=worker_id, bridge=bridge, gateway=gateway, private_key=private_key, budget=budget)
        if gateway_url is not None:
            gateway_url = normalize_gateway_url(gateway_url, allow_insecure=allow_insecure_lan)
        self.lead = lead  # the persistent Engineering Lead, or None when it is not configured
        self.allow_insecure_lan = allow_insecure_lan
        self.gateway_url = gateway_url
        self.heartbeat_interval = heartbeat_interval
        self.max_backoff = max_backoff
        self.ssl_context = ssl_context
        self.poll_interval = poll_interval
        self._ws = None
        self._is_connected = False
        self._undelivered = None  # a signed result the Gateway has not acknowledged yet
        self._startup_failures = []  # (job_id, message) for jobs cut off by a restart; reported once after reconnecting
        self._running = False
        self._reconnect_attempts = 0

    def add_startup_failures(self, failures):
        self._startup_failures.extend((str(job_id), str(message)) for job_id, message in failures)

    def report_startup_failures(self):
        """Tell the Gateway about jobs this Worker lost before a restart, so they are not left RUNNING."""
        while self._startup_failures:
            job_id, message = self._startup_failures[0]
            self._send({
                'message_type': MSG_JOB_FAILURE,
                'payload': {'job_id': job_id, 'error': redact_secret_values(message)},
            })
            self._recv()
            self._startup_failures.pop(0)

    def connect_ws(self, ws_client=None):
        """Connect to the gateway WebSocket endpoint.

        ws_client can be a pre-connected websocket client (e.g. Starlette TestClient websocket)
        or None to connect using websocket-client library.
        """
        if ws_client is not None:
            self._ws = ws_client
            self._is_connected = True
        else:
            import websocket

            if not self.gateway_url:
                raise WorkerConnectionError('gateway_url must be provided for network connection.')

            ws_url = websocket_url(normalize_gateway_url(self.gateway_url, allow_insecure=self.allow_insecure_lan))
            sslopt = certificate_options(ws_url, self.ssl_context)

            try:
                self._ws = websocket.create_connection(ws_url, sslopt=sslopt, timeout=10, redirect_limit=0)
                self._is_connected = True
                self._reconnect_attempts = 0
            except Exception as err:
                self._is_connected = False
                raise WorkerConnectionError(f'Failed to connect to Gateway WebSocket: {err}') from err

        # Handshake: register worker
        self._send({
            'message_type': MSG_WORKER_REGISTER,
            'payload': {
                'worker_id': self.worker_id,
                'capabilities': self.capabilities,
            },
        })

        challenge_msg = self._recv()
        if challenge_msg.get('message_type') != MSG_WORKER_CHALLENGE:
            self.disconnect()
            raise WorkerConnectionError(f'Expected WORKER_CHALLENGE from gateway, got: {challenge_msg}')

        challenge_payload = challenge_msg.get('payload', {})
        nonce = challenge_payload.get('nonce')
        challenge_text = challenge_payload.get('message')
        if not nonce or not challenge_text:
            self.disconnect()
            raise WorkerConnectionError('Malformed WORKER_CHALLENGE from gateway.')

        # Sign challenge with worker private key
        sig_raw = self.private_key.sign(challenge_text.encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')

        # Send WORKER_AUTH
        self._send({
            'message_type': MSG_WORKER_AUTH,
            'payload': {
                'worker_id': self.worker_id,
                'nonce': nonce,
                'signature': sig_b64,
            },
        })

        ack = self._recv()
        if ack.get('status') != 'REGISTERED':
            self.disconnect()
            raise WorkerConnectionError(f'Gateway rejected worker registration: {ack}')

        self._redeliver_undelivered()
        return True

    def disconnect(self):
        self._is_connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def send_heartbeat(self) -> dict:
        self._send({
            'message_type': MSG_HEARTBEAT,
            'payload': {'worker_id': self.worker_id},
        })
        return self._recv()

    def poll_and_execute_one_job(self) -> Optional[dict]:
        self.report_startup_failures()
        self._send({
            'message_type': 'JOB_POLL',
            'payload': {'worker_id': self.worker_id},
        })
        msg = self._recv()
        if msg.get('message_type') != MSG_JOB_ASSIGN:
            return None

        job_data = msg['payload']
        job_id = job_data.get('job_id') if isinstance(job_data, dict) else None
        try:
            self._intake(job_data)
        except (ValueError, BudgetExceeded) as err:
            self._send({
                'message_type': MSG_JOB_FAILURE,
                'payload': {'job_id': job_id, 'error': redact_secret_values(f'Refused: {err}')},
            })
            self._recv()
            return None
        try:
            developer_id = job_data['developer_id']
            self._send({
                'message_type': MSG_JOB_ACK,
                'payload': {'job_id': job_id, 'worker_id': self.worker_id},
            })
            # Report progress
            self._send({
                'message_type': MSG_JOB_PROGRESS,
                'payload': {'job_id': job_id, 'status': 'RUNNING'},
            })

            result = self._run_keeping_connection_alive(lambda: self.run_job_payload(job_data))

            status = result.get('status', 'SUCCEEDED')
            result = sanitize_worker_result(result)
            result = attest_result(self.private_key, job_id, developer_id, self.worker_id, status, result)
            envelope = ResultEnvelope.create(
                private_key=self.private_key,
                job_id=job_id,
                developer_id=developer_id,
                worker_id=self.worker_id,
                status=status,
                result=result,
            )
            self._deliver_result(envelope)
            return result

        except ResultNotDelivered:
            raise  # the job succeeded; its result is held for redelivery, so do not report a failure
        except Exception as err:
            self._send({
                'message_type': MSG_JOB_FAILURE,
                'payload': {'job_id': job_id, 'error': redact_secret_values(f'{type(err).__name__}: {err}')},
            })
            self._recv()
            raise
        finally:
            self._release()

    def run_job_payload(self, job_data: dict) -> dict:
        """Run one Gateway job locally. `lead` jobs go to the persistent Lead; every other job goes to the bridge."""
        if job_data.get('task_type') == 'lead':
            if self.lead is None:
                raise LeadNotConfigured('The persistent Engineering Lead is not configured on this Worker; the job is refused.')
            return self.lead.run_turn(job_data)
        if not self.bridge:
            return {
                'status': 'SUCCEEDED',
                'output': f"Simulated bridge execution for job {job_data['job_id']}",
                'task': job_data['task'],
            }
        scope = job_data.get('scope')
        modules = scope.get('modules') if isinstance(scope, dict) else None
        if not isinstance(modules, list) or not modules:
            # Fail closed: a job without the requester's authorized modules is refused before any work starts.
            raise ValueError('The job carries no authorized module scope; the Worker refuses it.')
        record = self.bridge.create(
            task=job_data['task'],
            task_type=job_data.get('task_type', 'docs'),
            developer_id=job_data['developer_id'],
            branch=job_data.get('branch'),
            base_commit=job_data.get('base_commit'),
            module_scope=modules,
        )
        local_job_id = record['job_id']
        self.bridge.execute(local_job_id)
        return self.bridge.get(local_job_id)

    def _deliver_result(self, envelope):
        """Send a signed result and wait for the Gateway's reply. On a connection failure keep the result for redelivery."""
        try:
            self._send({'message_type': MSG_JOB_RESULT, 'payload': envelope})
            reply = self._recv()
        except Exception as err:
            self._undelivered = envelope
            raise ResultNotDelivered(f'Result for job {envelope.get("job_id")} was not acknowledged: {err}') from err
        self._undelivered = None
        if reply.get('message_type') != 'JOB_RESULT_ACK':
            logger.warning(f'Gateway did not accept the result for job {envelope.get("job_id")}: {reply.get("error", reply)}')

    def _redeliver_undelivered(self):
        if self._undelivered is not None:
            logger.info(f'Redelivering the result for job {self._undelivered.get("job_id")} after reconnecting.')
            self._deliver_result(self._undelivered)

    def _run_keeping_connection_alive(self, work):
        """Run `work()` in a thread while this thread keeps reading the WebSocket.

        The Gateway pings on a timer and drops a connection that does not answer. websocket-client answers a ping
        only while it is reading, and a Claude run can last minutes, so without this the Gateway closes the
        connection mid-job and the finished result cannot be delivered. The Gateway sends nothing unprompted, so
        anything read here besides control frames is unexpected and ignored.
        """
        box = {}

        def target():
            try:
                box['value'] = work()
            except BaseException as err:
                box['error'] = err

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        servicing = hasattr(self._ws, 'settimeout') and hasattr(self._ws, 'recv')
        if servicing:
            import websocket  # only the real client reaches here; Gateway-only hosts never import it
        next_heartbeat = time.monotonic() + self.heartbeat_interval
        while thread.is_alive():
            ws = self._ws
            if not servicing or ws is None:
                thread.join(timeout=1.0)
                continue
            try:
                if time.monotonic() >= next_heartbeat:
                    # Keeps the Gateway from reaping this Worker mid-job. The reply is read below and ignored.
                    self._send({'message_type': MSG_HEARTBEAT, 'payload': {'worker_id': self.worker_id}})
                    next_heartbeat = time.monotonic() + self.heartbeat_interval
                ws.settimeout(1.0)
                ws.recv()
            except websocket.WebSocketTimeoutException:
                pass
            except Exception as err:
                logger.warning(f'Connection lost while a job was running: {err}. The job will finish; its result may not be deliverable.')
                servicing = False
        thread.join()
        if servicing and self._ws is not None:
            self._ws.settimeout(10)
        if 'error' in box:
            raise box['error']
        return box['value']

    def run_reconnect_loop(
        self,
        max_cycles: Optional[int] = 1,
        backoff_base: float = 0.1,
        poll_interval: Optional[float] = None,
    ):
        """Worker event loop with bounded exponential backoff reconnection and idle sleep."""
        self._running = True
        cycle = 0
        backoff = backoff_base
        idle_sleep = poll_interval if poll_interval is not None else self.poll_interval
        while self._running:
            if max_cycles is not None and cycle >= max_cycles:
                break
            cycle += 1
            try:
                if not self._is_connected:
                    self.connect_ws()
                self.send_heartbeat()
                job_res = self.poll_and_execute_one_job()
                backoff = backoff_base  # reset on success
                if job_res is None and self._running:
                    time.sleep(idle_sleep)
            except Exception as err:
                logger.warning(f'Worker loop encountered error: {err}. Reconnecting with backoff {backoff:.2f}s')
                self.disconnect()
                if self._running:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, self.max_backoff)

    def stop(self):
        """Stop worker execution loop gracefully."""
        self._running = False
        self.disconnect()


    def _send(self, data: dict):
        if hasattr(self._ws, 'send_json'):
            self._ws.send_json(data)
        elif hasattr(self._ws, 'send'):
            self._ws.send(json.dumps(data))
        else:
            raise WorkerConnectionError('No active WebSocket connection.')

    def _recv(self) -> dict:
        if hasattr(self._ws, 'receive_json'):
            return self._ws.receive_json()
        elif hasattr(self._ws, 'recv'):
            raw = self._ws.recv()
            return json.loads(raw)
        else:
            raise WorkerConnectionError('No active WebSocket connection.')


def load_worker_private_key(
    key_file: Optional[str] = None,
    key_b64: Optional[str] = None,
) -> ed25519.Ed25519PrivateKey:
    """Load an Ed25519 private key from a file or base64 string without generating a new random key."""
    if key_b64 and key_b64.strip():
        raw = base64.b64decode(key_b64.strip(), validate=True)
        if len(raw) == 32:
            return ed25519.Ed25519PrivateKey.from_private_bytes(raw)
        from cryptography.hazmat.primitives import serialization
        return serialization.load_der_private_key(raw, password=None)

    if key_file and os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            data = f.read()
        if len(data) == 32:
            return ed25519.Ed25519PrivateKey.from_private_bytes(data)
        from cryptography.hazmat.primitives import serialization
        try:
            return serialization.load_pem_private_key(data, password=None)
        except Exception:
            return ed25519.Ed25519PrivateKey.from_private_bytes(data[:32])

    raise ValueError('A valid SYNORA_WORKER_KEY_FILE or SYNORA_WORKER_PRIVATE_KEY_B64 is required.')
