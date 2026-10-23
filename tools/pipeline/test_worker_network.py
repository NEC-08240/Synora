# Tests for Outbound Worker Network Communication (Milestone D)
import base64
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .team_registry import DeveloperEntry, TeamRegistry
from .worker import OutboundWorker
from .worker_registry import WorkerRegistry


class TestWorkerNetwork(unittest.TestCase):
    def setUp(self):
        self.worker_priv = ed25519.Ed25519PrivateKey.generate()
        self.worker_pub_b64 = base64.b64encode(self.worker_priv.public_key().public_bytes_raw()).decode()
        self.worker_registry = WorkerRegistry()
        self.worker_registry.enroll('worker-net-1', self.worker_pub_b64)

        self.registry = TeamRegistry()
        dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub)
        self.registry.register(self.dev)

        self.gateway = Gateway(registry=self.registry, worker_registry=self.worker_registry)
        self.app = create_gateway_app(self.gateway)
        self.client = TestClient(self.app)

        self.worker = OutboundWorker(worker_id='worker-net-1', private_key=self.worker_priv)

    def tearDown(self):
        self.worker.disconnect()
        self.gateway.queue.close()

    def test_outbound_worker_has_no_listening_ports(self):
        # Verification of Absolute Invariant:
        # Worker does not bind to any local socket or create any listening server.
        self.assertFalse(hasattr(self.worker, 'listen'))
        self.assertFalse(hasattr(self.worker, 'serve_forever'))
        self.assertIsNone(self.worker._ws)

    def test_websocket_registration_and_heartbeat(self):
        with self.client.websocket_connect('/ws/worker') as ws:
            connected = self.worker.connect_ws(ws)
            self.assertTrue(connected)

            # Send heartbeat
            hb_res = self.worker.send_heartbeat()
            self.assertEqual(hb_res['status'], 'PONG')
            self.assertEqual(hb_res['worker_id'], 'worker-net-1')

            # Verify gateway recorded heartbeat
            workers_status = self.gateway.get_worker_status()
            w_info = next(w for w in workers_status['workers'] if w['worker_id'] == 'worker-net-1')
            self.assertEqual(w_info['status'], 'active')

    def test_unregistered_worker_rejected_by_gateway(self):
        bad_worker = OutboundWorker(worker_id='unknown-worker-99')
        with self.client.websocket_connect('/ws/worker') as ws:
            with self.assertRaises(Exception):
                bad_worker.connect_ws(ws)

    def test_end_to_end_job_poll_execute_and_verify(self):
        # Enqueue job in gateway
        self.gateway.queue.enqueue({
            'job_id': 'job-ws-e2e',
            'developer_id': 'alice',
            'task': 'End to end websocket test task',
            'task_type': 'docs',
        })

        with self.client.websocket_connect('/ws/worker') as ws:
            self.worker.connect_ws(ws)
            exec_res = self.worker.poll_and_execute_one_job()
            self.assertIsNotNone(exec_res)
            self.assertEqual(exec_res['status'], 'SUCCEEDED')

        # Check job status in gateway
        job = self.gateway.queue.get_job('job-ws-e2e')
        self.assertEqual(job['status'], 'SUCCEEDED')
        self.assertEqual(job['worker_id'], 'worker-net-1')


if __name__ == '__main__':
    unittest.main()
