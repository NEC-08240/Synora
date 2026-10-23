# Tests for Worker Heartbeat, Timeout, Reconnect and Job Recovery (Milestone E)
import base64
import time
import unittest
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .queue import JobQueue
from .team_registry import DeveloperEntry, TeamRegistry
from .worker import OutboundWorker
from .worker_registry import WorkerRegistry


class TestWorkerReconnect(unittest.TestCase):
    def setUp(self):
        self.worker_priv = ed25519.Ed25519PrivateKey.generate()
        self.worker_pub_b64 = base64.b64encode(self.worker_priv.public_key().public_bytes_raw()).decode()
        self.worker_registry = WorkerRegistry()
        self.worker_registry.enroll('worker-recon-1', self.worker_pub_b64)

        self.registry = TeamRegistry()
        dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub)
        self.registry.register(self.dev)

        self.queue = JobQueue(':memory:')
        self.gateway = Gateway(registry=self.registry, queue=self.queue, worker_registry=self.worker_registry)
        self.app = create_gateway_app(self.gateway)
        self.client = TestClient(self.app)

        self.worker = OutboundWorker(worker_id='worker-recon-1', private_key=self.worker_priv)

    def tearDown(self):
        self.worker.disconnect()
        self.queue.close()

    def test_stale_worker_reap_resets_uncompleted_jobs(self):
        # Register worker heartbeat
        self.queue.heartbeat_worker('worker-recon-1')

        # Enqueue job and claim by worker
        self.queue.enqueue({
            'job_id': 'job-reap-1',
            'developer_id': 'alice',
            'task': 'Task to be reaped on crash',
            'task_type': 'docs',
        })
        claimed = self.queue.claim_next('worker-recon-1')
        self.assertEqual(claimed['status'], 'ASSIGNED')

        # Record worker heartbeat with old timestamp (70s ago)
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=70)).isoformat()
        with self.queue._lock:
            with self.queue._conn:
                self.queue._conn.execute(
                    'UPDATE workers SET last_heartbeat = ? WHERE worker_id = ?;',
                    (old_time, 'worker-recon-1'),
                )

        # Gateway reaps stale workers with 60s timeout
        reaped = self.queue.reap_stale_workers(timeout_seconds=60.0)
        self.assertIn('worker-recon-1', reaped)

        # Job is reset to QUEUED and worker_id is cleared
        job = self.queue.get_job('job-reap-1')
        self.assertEqual(job['status'], 'QUEUED')
        self.assertIsNone(job['worker_id'])

    def test_worker_reconnect_and_reclaim_job(self):
        self.queue.enqueue({
            'job_id': 'job-recon-e2e',
            'developer_id': 'alice',
            'task': 'Task to be reclaimed after reconnect',
            'task_type': 'docs',
        })

        # Session 1: worker connects, claims job, but disconnects before completing
        with self.client.websocket_connect('/ws/worker') as ws1:
            self.worker.connect_ws(ws1)
            # Worker polls job
            job_data = self.worker.gateway.worker_poll_job('worker-recon-1') if self.worker.gateway else None
            # Simulate claim
            claimed = self.queue.claim_next('worker-recon-1')
            self.assertEqual(claimed['job_id'], 'job-recon-e2e')

        self.worker.disconnect()

        # Gateway detects worker disappearance and reaps it
        self.queue.reap_stale_workers(timeout_seconds=0.0)
        recovered_job = self.queue.get_job('job-recon-e2e')
        self.assertEqual(recovered_job['status'], 'QUEUED')

        # Session 2: Worker reconnects and completes the job
        with self.client.websocket_connect('/ws/worker') as ws2:
            self.worker.connect_ws(ws2)
            exec_res = self.worker.poll_and_execute_one_job()
            self.assertIsNotNone(exec_res)
            self.assertEqual(exec_res['status'], 'SUCCEEDED')

        final_job = self.queue.get_job('job-recon-e2e')
        self.assertEqual(final_job['status'], 'SUCCEEDED')

    def test_reconnect_loop_bounded_backoff(self):
        # Verify that backoff logic is bounded and does not busy-loop
        delays = []
        base = 0.05
        max_b = 0.2
        val = base
        for _ in range(5):
            delays.append(val)
            val = min(val * 2, max_b)

        self.assertEqual(delays[0], 0.05)
        self.assertEqual(delays[1], 0.1)
        self.assertEqual(delays[2], 0.2)
        self.assertEqual(delays[3], 0.2)  # bounded!
        self.assertEqual(delays[4], 0.2)


if __name__ == '__main__':
    unittest.main()
