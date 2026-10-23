# Tests for Deployment Blockers & Fixes (Phase C Step 6)
import asyncio
import base64
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .audit import AuditLogger
from .gateway import Gateway, RecoveryScheduler
from .gateway_app import create_gateway_app
from .gateway_server import create_production_app, load_gateway_config
from .protocol import (
    MSG_JOB_ASSIGN,
    MSG_WORKER_AUTH,
    MSG_WORKER_CHALLENGE,
    MSG_WORKER_REGISTER,
)
from .queue import JobQueue
from .team_registry import DeveloperEntry, TeamRegistry
from .worker import OutboundWorker, WorkerConnectionError, load_worker_private_key
from .worker_daemon import create_worker_from_config, load_worker_config
from .worker_registry import WorkerRegistry


class TestGatewayServerConfig(unittest.TestCase):
    """Blocker 1: Gateway production entrypoint and persistent configuration tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name
        self._open_apps = []

        # Create dummy team registry
        self.dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(self.dev_priv.public_key().public_bytes_raw()).decode()
        self.team_reg = TeamRegistry()
        self.team_reg.register(DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub))
        self.team_path = os.path.join(self.tmp_dir, 'team_registry.json')
        self.team_reg.save(self.team_path)

        # Create dummy worker registry
        self.worker_priv = ed25519.Ed25519PrivateKey.generate()
        worker_pub = base64.b64encode(self.worker_priv.public_key().public_bytes_raw()).decode()
        self.worker_reg_path = os.path.join(self.tmp_dir, 'worker_registry.json')
        self.worker_reg = WorkerRegistry(self.worker_reg_path)
        self.worker_reg.enroll('worker-prod-1', worker_pub)

        self.db_path = os.path.join(self.tmp_dir, 'persistent_gateway.db')
        self.secret = 'a' * 32  # 32-byte secret

    def tearDown(self):
        for app in self._open_apps:
            if hasattr(app.state, 'gateway') and hasattr(app.state.gateway, 'queue'):
                app.state.gateway.queue.close()
        self._tmp.cleanup()

    def test_startup_with_valid_persistent_configuration(self):
        env = {
            'SYNORA_GATEWAY_HOST': '127.0.0.1',
            'SYNORA_GATEWAY_PORT': '8000',
            'SYNORA_GATEWAY_SIGNING_SECRET': self.secret,
            'SYNORA_GATEWAY_REGISTRY_PATH': self.team_path,
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
            'SYNORA_GATEWAY_DB_PATH': self.db_path,
            'SYNORA_GATEWAY_AUDIT_LOG_PATH': os.path.join(self.tmp_dir, 'audit.log'),
        }
        cfg = load_gateway_config(env)
        self.assertEqual(cfg['host'], '127.0.0.1')
        self.assertEqual(cfg['port'], 8000)
        self.assertEqual(cfg['db_path'], self.db_path)

        app = create_production_app(cfg)
        self._open_apps.append(app)
        self.assertIsNotNone(app)
        self.assertEqual(app.state.config['db_path'], self.db_path)

    def test_missing_required_secret_fails_safely(self):
        env = {
            'SYNORA_GATEWAY_REGISTRY_PATH': self.team_path,
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
        }
        with self.assertRaises(ValueError) as ctx:
            load_gateway_config(env)
        self.assertIn('SYNORA_GATEWAY_SIGNING_SECRET', str(ctx.exception))

    def test_short_secret_fails_safely(self):
        env = {
            'SYNORA_GATEWAY_SIGNING_SECRET': 'too-short-secret',
            'SYNORA_GATEWAY_REGISTRY_PATH': self.team_path,
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
        }
        with self.assertRaises(ValueError) as ctx:
            load_gateway_config(env)
        self.assertIn('at least 32 bytes', str(ctx.exception))

    def test_missing_registry_path_fails_safely(self):
        env = {
            'SYNORA_GATEWAY_SIGNING_SECRET': self.secret,
            'SYNORA_GATEWAY_REGISTRY_PATH': os.path.join(self.tmp_dir, 'non_existent.json'),
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
        }
        with self.assertRaises(FileNotFoundError):
            load_gateway_config(env)

    def test_persistent_db_path_is_actually_used_and_survives_restart(self):
        env = {
            'SYNORA_GATEWAY_SIGNING_SECRET': self.secret,
            'SYNORA_GATEWAY_REGISTRY_PATH': self.team_path,
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
            'SYNORA_GATEWAY_DB_PATH': self.db_path,
        }
        cfg = load_gateway_config(env)

        # Instance 1: enqueue a job
        app1 = create_production_app(cfg)
        gw1 = app1.state.gateway
        job_id = gw1.queue.enqueue({
            'job_id': 'job-persist-test',
            'developer_id': 'alice',
            'task': 'Persistence check across restart',
            'task_type': 'docs',
        })
        gw1.queue.close()

        # Instance 2 (restart simulation on same DB): job must still be present
        app2 = create_production_app(cfg)
        gw2 = app2.state.gateway
        job = gw2.queue.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['task'], 'Persistence check across restart')
        self.assertEqual(job['status'], 'QUEUED')
        gw2.queue.close()

    def test_persistent_signing_secret_survives_restart(self):
        env = {
            'SYNORA_GATEWAY_SIGNING_SECRET': self.secret,
            'SYNORA_GATEWAY_REGISTRY_PATH': self.team_path,
            'SYNORA_GATEWAY_WORKER_REGISTRY_PATH': self.worker_reg_path,
            'SYNORA_GATEWAY_DB_PATH': self.db_path,
        }
        cfg = load_gateway_config(env)

        # Server 1 issues a token to Alice
        app1 = create_production_app(cfg)
        gw1 = app1.state.gateway
        chal = gw1.request_challenge('alice')
        sig = base64.b64encode(self.dev_priv.sign(chal['message'].encode())).decode()
        token = gw1.authenticate('alice', chal['nonce'], sig)
        self.assertTrue(len(token) > 0)
        gw1.queue.close()

        # Server 2 (restart with same secret) accepts Alice's token
        app2 = create_production_app(cfg)
        gw2 = app2.state.gateway
        dev = gw2.verify_caller(token)
        self.assertEqual(dev.developer_id, 'alice')
        gw2.queue.close()


class TestWorkerDaemonConfig(unittest.TestCase):
    """Blocker 2: Worker standalone runner, key loading, and anti-busyloop tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name
        self._open_apps = []
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.raw_priv = self.priv.private_bytes_raw()
        self.key_file = os.path.join(self.tmp_dir, 'worker.key')
        with open(self.key_file, 'wb') as f:
            f.write(self.raw_priv)

    def tearDown(self):
        for app in self._open_apps:
            if hasattr(app.state, 'gateway') and hasattr(app.state.gateway, 'queue'):
                app.state.gateway.queue.close()
        self._tmp.cleanup()

    def test_persistent_key_is_loaded_from_file(self):
        loaded_key = load_worker_private_key(key_file=self.key_file)
        self.assertEqual(loaded_key.private_bytes_raw(), self.raw_priv)

    def test_persistent_key_is_loaded_from_b64(self):
        b64_str = base64.b64encode(self.raw_priv).decode()
        loaded_key = load_worker_private_key(key_b64=b64_str)
        self.assertEqual(loaded_key.private_bytes_raw(), self.raw_priv)

    def test_missing_key_fails_safely(self):
        env = {
            'SYNORA_GATEWAY_URL': 'wss://127.0.0.1:8000',
        }
        with self.assertRaises(ValueError) as ctx:
            load_worker_config(env)
        self.assertIn('SYNORA_WORKER_KEY_FILE', str(ctx.exception))

    def test_same_worker_identity_survives_restart(self):
        env = {
            'SYNORA_WORKER_ID': 'worker-persistent-1',
            'SYNORA_GATEWAY_URL': 'wss://127.0.0.1:8000',
            'SYNORA_WORKER_KEY_FILE': self.key_file,
            'SYNORA_BRIDGE_REPO': self.tmp_dir,
        }
        cfg1 = load_worker_config(env)
        w1 = create_worker_from_config(cfg1)

        cfg2 = load_worker_config(env)
        w2 = create_worker_from_config(cfg2)

        # Worker public keys must be identical across instances
        self.assertEqual(
            w1.private_key.public_key().public_bytes_raw(),
            w2.private_key.public_key().public_bytes_raw(),
        )

    def test_empty_queue_does_not_busy_loop(self):
        # Verify that when job_poll is empty, worker sleeps for poll_interval
        worker = OutboundWorker(worker_id='w-busyloop-test', private_key=self.priv, poll_interval=0.08)

        # Mock poll_and_execute_one_job to return None (empty queue)
        worker.poll_and_execute_one_job = lambda: None
        worker.connect_ws = lambda: True
        worker.send_heartbeat = lambda: {'status': 'PONG'}

        t0 = time.time()
        # Run 2 cycles with empty queue; each must sleep ~0.08s
        worker.run_reconnect_loop(max_cycles=2, poll_interval=0.08)
        elapsed = time.time() - t0

        self.assertGreaterEqual(elapsed, 0.15)  # 2 * 0.08s = 0.16s, proving idle sleep!

    def test_reconnect_uses_bounded_backoff(self):
        worker = OutboundWorker(worker_id='w-backoff-test', private_key=self.priv, max_backoff=0.3)

        def mock_failing_connect():
            raise ConnectionError('Simulated network failure')

        worker.connect_ws = mock_failing_connect

        t0 = time.time()
        # 3 failures with backoff_base=0.05: 0.05 + 0.10 + 0.20 = 0.35s
        worker.run_reconnect_loop(max_cycles=3, backoff_base=0.05)
        elapsed = time.time() - t0

        self.assertGreaterEqual(elapsed, 0.30)


class TestWorkerWebSocketAuthentication(unittest.TestCase):
    """Blocker 3: Authenticate Worker WebSocket registration with Ed25519 challenge-response."""

    def setUp(self):
        self.worker_priv = ed25519.Ed25519PrivateKey.generate()
        self.worker_pub_b64 = base64.b64encode(self.worker_priv.public_key().public_bytes_raw()).decode()
        self.worker_registry = WorkerRegistry()
        self.worker_registry.enroll('worker-auth-1', self.worker_pub_b64)

        # Enrolled suspended worker
        self.susp_priv = ed25519.Ed25519PrivateKey.generate()
        susp_pub_b64 = base64.b64encode(self.susp_priv.public_key().public_bytes_raw()).decode()
        self.worker_registry.enroll('worker-susp-1', susp_pub_b64, status='suspended')

        self.registry = TeamRegistry()
        dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub)
        self.registry.register(self.dev)

        self.gateway = Gateway(registry=self.registry, worker_registry=self.worker_registry)
        self.app = create_gateway_app(self.gateway, enable_recovery_scheduler=False)
        self.client = TestClient(self.app)

        self.worker = OutboundWorker(worker_id='worker-auth-1', private_key=self.worker_priv)

    def tearDown(self):
        self.worker.disconnect()
        self.gateway.queue.close()

    def test_valid_worker_authentication_handshake(self):
        with self.client.websocket_connect('/ws/worker') as ws:
            connected = self.worker.connect_ws(ws)
            self.assertTrue(connected)
            self.assertTrue(self.worker._is_connected)

            # Worker should be online in gateway
            workers = self.gateway.get_worker_status()
            w_info = next(w for w in workers['workers'] if w['worker_id'] == 'worker-auth-1')
            self.assertEqual(w_info['status'], 'active')

    def test_unknown_worker_rejected(self):
        unknown_worker = OutboundWorker(worker_id='unknown-worker-999')
        with self.client.websocket_connect('/ws/worker') as ws:
            with self.assertRaises(WorkerConnectionError) as ctx:
                unknown_worker.connect_ws(ws)
            self.assertIn('not registered', str(ctx.exception))

    def test_suspended_worker_rejected(self):
        susp_worker = OutboundWorker(worker_id='worker-susp-1', private_key=self.susp_priv)
        with self.client.websocket_connect('/ws/worker') as ws:
            with self.assertRaises(WorkerConnectionError) as ctx:
                susp_worker.connect_ws(ws)
            self.assertIn('suspended', str(ctx.exception))

    def test_invalid_signature_rejected(self):
        # Attacker tries to register as worker-auth-1 using wrong private key
        attacker_priv = ed25519.Ed25519PrivateKey.generate()
        imposter = OutboundWorker(worker_id='worker-auth-1', private_key=attacker_priv)

        with self.client.websocket_connect('/ws/worker') as ws:
            with self.assertRaises(WorkerConnectionError) as ctx:
                imposter.connect_ws(ws)
            self.assertIn('Worker authentication failed', str(ctx.exception))

    def test_replayed_challenge_rejected(self):
        with self.client.websocket_connect('/ws/worker') as ws:
            # 1. Send WORKER_REGISTER
            ws.send_json({'message_type': MSG_WORKER_REGISTER, 'payload': {'worker_id': 'worker-auth-1'}})
            chal_msg = ws.receive_json()
            self.assertEqual(chal_msg['message_type'], MSG_WORKER_CHALLENGE)
            nonce = chal_msg['payload']['nonce']
            msg_to_sign = chal_msg['payload']['message']

            # Sign
            sig = base64.b64encode(self.worker_priv.sign(msg_to_sign.encode())).decode()

            # First use: valid
            ws.send_json({
                'message_type': MSG_WORKER_AUTH,
                'payload': {'worker_id': 'worker-auth-1', 'nonce': nonce, 'signature': sig},
            })
            ack = ws.receive_json()
            self.assertEqual(ack.get('status'), 'REGISTERED')

        # Second connection attempts to replay the same nonce and signature
        with self.client.websocket_connect('/ws/worker') as ws2:
            ws2.send_json({'message_type': MSG_WORKER_REGISTER, 'payload': {'worker_id': 'worker-auth-1'}})
            chal2 = ws2.receive_json()
            self.assertEqual(chal2['message_type'], MSG_WORKER_CHALLENGE)

            # Replay the old nonce and sig
            ws2.send_json({
                'message_type': MSG_WORKER_AUTH,
                'payload': {'worker_id': 'worker-auth-1', 'nonce': nonce, 'signature': sig},
            })
            err_msg = ws2.receive_json()
            self.assertIn('authentication failed', err_msg.get('error', '').lower())

    def test_identity_mismatch_rejected(self):
        # Register as worker-auth-1, but send WORKER_AUTH with worker-auth-2
        with self.client.websocket_connect('/ws/worker') as ws:
            ws.send_json({'message_type': MSG_WORKER_REGISTER, 'payload': {'worker_id': 'worker-auth-1'}})
            chal_msg = ws.receive_json()
            nonce = chal_msg['payload']['nonce']
            msg_to_sign = chal_msg['payload']['message']
            sig = base64.b64encode(self.worker_priv.sign(msg_to_sign.encode())).decode()

            ws.send_json({
                'message_type': MSG_WORKER_AUTH,
                'payload': {'worker_id': 'different-worker-id', 'nonce': nonce, 'signature': sig},
            })
            err_msg = ws.receive_json()
            self.assertIn('Worker identity mismatch', err_msg.get('error', ''))

    def test_malformed_registration_message_rejected(self):
        with self.client.websocket_connect('/ws/worker') as ws:
            # Send wrong first message (e.g. HEARTBEAT before registration)
            ws.send_json({'message_type': 'HEARTBEAT', 'payload': {}})
            err = ws.receive_json()
            self.assertIn('First message must be WORKER_REGISTER', err.get('error', ''))

    def test_unauthenticated_socket_cannot_reach_job_polling(self):
        # An adversary connects and immediately attempts JOB_POLL without authentication
        with self.client.websocket_connect('/ws/worker') as ws:
            ws.send_json({'message_type': 'JOB_POLL', 'payload': {'worker_id': 'worker-auth-1'}})
            err = ws.receive_json()
            self.assertIn('First message must be WORKER_REGISTER', err.get('error', ''))


class TestRecoveryScheduler(unittest.TestCase):
    """Blocker 4: Schedule stale-worker and job recovery tests."""

    def setUp(self):
        self.queue = JobQueue(':memory:')
        self.audit = AuditLogger()
        self.scheduler = RecoveryScheduler(
            queue=self.queue,
            interval_seconds=0.05,
            worker_stale_timeout=0.1,
            job_ttl_seconds=0.2,
            audit=self.audit,
        )

    def tearDown(self):
        if self.scheduler.is_running:
            asyncio.run(self.scheduler.stop())
        self.queue.close()

    def test_stale_workers_are_reaped_and_jobs_become_reclaimable(self):
        # Worker claims job
        self.queue.heartbeat_worker('worker-drop-1')
        self.queue.enqueue({
            'job_id': 'job-drop-test',
            'developer_id': 'alice',
            'task': 'Task to be reaped by scheduler',
            'task_type': 'docs',
        })
        claimed = self.queue.claim_next('worker-drop-1')
        self.assertEqual(claimed['status'], 'ASSIGNED')

        # Simulate stale heartbeat (set to 10s ago)
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with self.queue._lock:
            with self.queue._conn:
                self.queue._conn.execute('UPDATE workers SET last_heartbeat = ? WHERE worker_id = ?;', (old_time, 'worker-drop-1'))

        # Run scheduler once
        reaped, expired = asyncio.run(self.scheduler.run_once())
        self.assertIn('worker-drop-1', reaped)

        # Job must be reset to QUEUED and reclaimable
        job = self.queue.get_job('job-drop-test')
        self.assertEqual(job['status'], 'QUEUED')
        self.assertIsNone(job['worker_id'])

        # New worker can claim it
        self.queue.heartbeat_worker('worker-drop-2')
        claimed2 = self.queue.claim_next('worker-drop-2')
        self.assertEqual(claimed2['job_id'], 'job-drop-test')
        self.assertEqual(claimed2['status'], 'ASSIGNED')

    def test_expired_jobs_are_handled_correctly(self):
        self.queue.enqueue({
            'job_id': 'job-ttl-test',
            'developer_id': 'alice',
            'task': 'Task with TTL expired',
            'task_type': 'docs',
        })
        # Simulate job created 100s ago
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        with self.queue._lock:
            with self.queue._conn:
                self.queue._conn.execute('UPDATE jobs SET created_at = ? WHERE job_id = ?;', (old_time, 'job-ttl-test'))

        reaped, expired = asyncio.run(self.scheduler.run_once())
        self.assertIn('job-ttl-test', expired)

        job = self.queue.get_job('job-ttl-test')
        self.assertEqual(job['status'], 'EXPIRED')
        self.assertIn('exceeded TTL', job['error'])

    def test_scheduler_lifecycle_and_duplicate_prevention(self):
        async def _test():
            self.assertFalse(self.scheduler.is_running)

            # Start scheduler
            self.scheduler.start()
            self.assertTrue(self.scheduler.is_running)

            # Starting again should be a no-op (no duplicate task created)
            task1 = self.scheduler._task
            self.scheduler.start()
            self.assertIs(self.scheduler._task, task1)

            # Wait briefly and stop cleanly
            await asyncio.sleep(0.08)
            await self.scheduler.stop()
            self.assertFalse(self.scheduler.is_running)
            self.assertIsNone(self.scheduler._task)

        asyncio.run(_test())


if __name__ == '__main__':
    unittest.main()
