"""Long jobs: results must survive the Gateway's keepalive and a dropped connection.

A job that runs longer than the Gateway's WebSocket keepalive must still deliver its result.

uvicorn pings every ws_ping_interval seconds and closes the connection when no pong arrives within
ws_ping_timeout (20 s each by default). A Worker that stops reading the socket while Claude runs never
answers, so the Gateway dropped it and the finished job's result was lost (the job stayed RUNNING).
This runs a real TLS uvicorn Gateway with a 1 s keepalive and a real OutboundWorker with a slow stand-in bridge.
A result whose connection dies before the Gateway acknowledges it is redelivered after reconnecting.
Run: python -m unittest tools.pipeline.test_worker_long_jobs -v
"""

import base64
import socket
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives.asymmetric import ed25519

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .team_registry import DeveloperEntry, TeamRegistry
from .tls_config import generate_ephemeral_test_cert
from .worker import OutboundWorker
from .worker_registry import WorkerRegistry

JOB_SECONDS = 6
KEEPALIVE_SECONDS = 1


class SlowBridge:
    """Stands in for Bridge: takes JOB_SECONDS to 'run Claude' and then reports success."""

    def __init__(self):
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return {"job_id": "local-1"}

    def execute(self, job_id):
        time.sleep(JOB_SECONDS)

    def get(self, job_id):
        return {"status": "SUCCEEDED", "changed_files": ["docs/agent-bridge/slow.md"], "base_commit": None}

    def resolve_base(self, requested):
        return requested


class OpenBudget:
    def admit(self):
        pass

    def finish(self):
        pass


class LongJobTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        cert, key = generate_ephemeral_test_cert(self._tmp.name, common_name="localhost", ip_addresses=["127.0.0.1"], valid_days=1)
        worker_key = ed25519.Ed25519PrivateKey.generate()
        workers = WorkerRegistry()
        workers.enroll("worker-slow", base64.b64encode(worker_key.public_key().public_bytes_raw()).decode())
        team = TeamRegistry()
        dev_pub = base64.b64encode(ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()
        team.register(DeveloperEntry("alice", "Alice", "alice-gh", "developer", "active", public_key_ed25519=dev_pub))
        self.gateway = Gateway(registry=team, worker_registry=workers)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = uvicorn.Config(
            create_gateway_app(self.gateway), host="127.0.0.1", port=port, ssl_certfile=cert, ssl_keyfile=key,
            ws="wsproto", ws_ping_interval=KEEPALIVE_SECONDS, ws_ping_timeout=KEEPALIVE_SECONDS, log_level="error",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.server.started, "test Gateway did not start")

        self.bridge = SlowBridge()
        self.worker = OutboundWorker(
            worker_id="worker-slow", gateway_url=f"wss://localhost:{port}", private_key=worker_key, bridge=self.bridge,
            budget=OpenBudget(), ssl_context=ssl.create_default_context(cafile=cert),
        )

    def tearDown(self):
        self.worker.disconnect()
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.gateway.queue.close()
        self._tmp.cleanup()

    def test_a_job_longer_than_the_keepalive_still_delivers_its_signed_result(self):
        self.gateway.queue.enqueue({
            "job_id": "job-slow", "developer_id": "alice", "task": "A task that takes a while to run.", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]},
            "branch": "feature/slow", "base_commit": "",
        })
        self.worker.connect_ws()

        result = self.worker.poll_and_execute_one_job()

        self.assertEqual(result["status"], "SUCCEEDED")
        job = self.gateway.queue.get_job("job-slow")
        self.assertEqual(job["status"], "SUCCEEDED")
        self.assertIn("attestation", job["result"])

    def test_the_worker_is_still_connected_after_a_long_job(self):
        self.gateway.queue.enqueue({
            "job_id": "job-slow-2", "developer_id": "alice", "task": "Another task that takes a while.", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]},
            "branch": "feature/slow", "base_commit": "",
        })
        self.worker.connect_ws()
        self.worker.poll_and_execute_one_job()

        self.assertEqual(self.worker.send_heartbeat()["status"], "PONG")

    def test_a_result_whose_connection_dies_before_acknowledgement_is_redelivered_after_reconnecting(self):
        self.gateway.queue.enqueue({
            "job_id": "job-cut", "developer_id": "alice", "task": "A task whose connection is cut mid-run.", "task_type": "docs", "scope": {"modules": ["docs/"], "branches": ["feature/*"]},
            "branch": "feature/cut", "base_commit": "",
        })
        self.worker.connect_ws()
        cutter = threading.Timer(2.0, lambda: self.worker._ws.sock.shutdown(socket.SHUT_RDWR))
        cutter.start()

        with self.assertRaises(ConnectionError):
            self.worker.poll_and_execute_one_job()

        self.assertNotEqual(self.gateway.queue.get_job("job-cut")["status"], "SUCCEEDED")
        self.assertIsNotNone(self.worker._undelivered)
        self.worker.disconnect()
        self.worker.connect_ws()

        job = self.gateway.queue.get_job("job-cut")
        self.assertEqual(job["status"], "SUCCEEDED")
        self.assertIn("attestation", job["result"])
        self.assertIsNone(self.worker._undelivered)


if __name__ == "__main__":
    unittest.main()
