# Claude Worker daemon & Outbound Worker for Synora Agent Bridge
import json
import logging
import ssl
import time
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519

from .bridge import Bridge
from .protocol import (
    MSG_HEARTBEAT,
    MSG_JOB_ACK,
    MSG_JOB_ASSIGN,
    MSG_JOB_FAILURE,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_WORKER_REGISTER,
)
from .result_envelope import ResultEnvelope

logger = logging.getLogger(__name__)


class WorkerConnectionError(ConnectionError):
    pass


class ClaudeWorker:
    def __init__(
        self,
        worker_id: str,
        bridge: Optional[Bridge] = None,
        gateway: Any = None,
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
    ):
        self.worker_id = worker_id
        self.bridge = bridge
        self.gateway = gateway
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self.capabilities = {'supported_tasks': ['docs', 'code', 'review']}

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
                )
                local_job_id = record['job_id']
                self.bridge.execute(local_job_id)
                result = self.bridge.get(local_job_id)

            status = result.get('status', 'SUCCEEDED')
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
            self.gateway.worker_submit_failure(self.worker_id, job_id, f'{type(err).__name__}: {err}')
            raise


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
    ):
        super().__init__(worker_id=worker_id, bridge=bridge, gateway=gateway, private_key=private_key)
        self.gateway_url = gateway_url
        self.heartbeat_interval = heartbeat_interval
        self.max_backoff = max_backoff
        self.ssl_context = ssl_context
        self._ws = None
        self._is_connected = False
        self._reconnect_attempts = 0

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

            ws_url = self.gateway_url.replace('http://', 'ws://').replace('https://', 'wss://')
            if not ws_url.endswith('/ws/worker'):
                ws_url = ws_url.rstrip('/') + '/ws/worker'

            sslopt = None
            if self.ssl_context:
                sslopt = {'context': self.ssl_context}

            try:
                self._ws = websocket.create_connection(ws_url, sslopt=sslopt, timeout=10)
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
        ack = self._recv()
        if ack.get('status') != 'REGISTERED':
            self.disconnect()
            raise WorkerConnectionError(f'Gateway rejected worker registration: {ack}')

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
        self._send({
            'message_type': 'JOB_POLL',
            'payload': {'worker_id': self.worker_id},
        })
        msg = self._recv()
        if msg.get('message_type') != MSG_JOB_ASSIGN:
            return None

        job_data = msg['payload']
        job_id = job_data['job_id']
        developer_id = job_data['developer_id']
        task = job_data['task']
        task_type = job_data.get('task_type', 'docs')

        # Send ACK
        self._send({
            'message_type': MSG_JOB_ACK,
            'payload': {'job_id': job_id, 'worker_id': self.worker_id},
        })

        try:
            # Report progress
            self._send({
                'message_type': MSG_JOB_PROGRESS,
                'payload': {'job_id': job_id, 'status': 'RUNNING'},
            })

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
                )
                local_job_id = record['job_id']
                self.bridge.execute(local_job_id)
                result = self.bridge.get(local_job_id)

            status = result.get('status', 'SUCCEEDED')
            envelope = ResultEnvelope.create(
                private_key=self.private_key,
                job_id=job_id,
                developer_id=developer_id,
                worker_id=self.worker_id,
                status=status,
                result=result,
            )
            self._send({
                'message_type': MSG_JOB_RESULT,
                'payload': envelope,
            })
            ack = self._recv()
            return result

        except Exception as err:
            self._send({
                'message_type': MSG_JOB_FAILURE,
                'payload': {'job_id': job_id, 'error': f'{type(err).__name__}: {err}'},
            })
            self._recv()
            raise

    def run_reconnect_loop(self, max_cycles: int = 1, backoff_base: float = 0.1):
        """Worker event loop with bounded exponential backoff reconnection."""
        cycle = 0
        backoff = backoff_base
        while cycle < max_cycles:
            cycle += 1
            try:
                if not self._is_connected:
                    self.connect_ws()
                self.send_heartbeat()
                self.poll_and_execute_one_job()
                backoff = backoff_base  # reset on success
            except Exception as err:
                logger.warning(f'Worker loop encountered error: {err}. Reconnecting with backoff {backoff:.2f}s')
                self.disconnect()
                time.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff)

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
