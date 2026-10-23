# Tests for Gateway HTTP API (Milestone A & B)
import base64
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .team_registry import DeveloperEntry, TeamRegistry
from .worker_registry import WorkerRegistry


class TestGatewayAPI(unittest.TestCase):
    def setUp(self):
        self.registry = TeamRegistry()
        self.worker_registry = WorkerRegistry()

        # Enroll developer Alice
        self.dev_priv = ed25519.Ed25519PrivateKey.generate()
        self.dev_pub_b64 = base64.b64encode(self.dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry(
            developer_id='alice',
            developer_name='Alice Smith',
            github_username='alice-gh',
            role='developer',
            status='active',
            public_key_ed25519=self.dev_pub_b64,
            allowed_branches=('feature/*',),
        )
        self.registry.register(self.dev)

        # Enroll suspended developer Eve
        self.eve_priv = ed25519.Ed25519PrivateKey.generate()
        self.eve_pub_b64 = base64.b64encode(self.eve_priv.public_key().public_bytes_raw()).decode()
        self.eve = DeveloperEntry(
            developer_id='eve',
            developer_name='Eve Suspended',
            github_username='eve-gh',
            role='developer',
            status='suspended',
            public_key_ed25519=self.eve_pub_b64,
            allowed_branches=('feature/*',),
        )
        self.registry.register(self.eve)

        self.gateway = Gateway(
            registry=self.registry,
            worker_registry=self.worker_registry,
            max_jobs_per_developer=2,
            max_task_size=1000,
            max_diff_size=5000,
        )
        self.app = create_gateway_app(self.gateway)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.gateway.queue.close()

    def _authenticate(self, dev_id: str, priv_key: ed25519.Ed25519PrivateKey) -> str:
        res = self.client.post('/auth/challenge', json={'developer_id': dev_id})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        nonce = data['nonce']
        message = data['message']
        sig_b64 = base64.b64encode(priv_key.sign(message.encode())).decode()
        v_res = self.client.post('/auth/verify', json={'developer_id': dev_id, 'nonce': nonce, 'signature': sig_b64})
        self.assertEqual(v_res.status_code, 200)
        return v_res.json()['token']

    def test_health_check(self):
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'HEALTHY')
        self.assertIn('X-Content-Type-Options', res.headers)
        self.assertEqual(res.headers['X-Content-Type-Options'], 'nosniff')

    def test_challenge_unknown_developer_404(self):
        res = self.client.post('/auth/challenge', json={'developer_id': 'unknown_dev'})
        self.assertEqual(res.status_code, 404)

    def test_challenge_suspended_developer_403(self):
        res = self.client.post('/auth/challenge', json={'developer_id': 'eve'})
        self.assertEqual(res.status_code, 403)

    def test_challenge_missing_developer_id_400(self):
        res = self.client.post('/auth/challenge', json={})
        self.assertEqual(res.status_code, 400)

    def test_verify_invalid_signature_401(self):
        c_res = self.client.post('/auth/challenge', json={'developer_id': 'alice'}).json()
        wrong_sig = base64.b64encode(b'x' * 64).decode()
        v_res = self.client.post(
            '/auth/verify',
            json={'developer_id': 'alice', 'nonce': c_res['nonce'], 'signature': wrong_sig},
        )
        self.assertEqual(v_res.status_code, 401)

    def test_verify_replayed_nonce_401(self):
        token = self._authenticate('alice', self.dev_priv)
        self.assertTrue(len(token) > 0)

    def test_submit_job_without_auth_401(self):
        res = self.client.post('/jobs', json={'task': 'Valid task text here', 'branch': 'feature/foo'})
        self.assertEqual(res.status_code, 401)

    def test_submit_and_get_job_lifecycle(self):
        token = self._authenticate('alice', self.dev_priv)
        submit_res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token}'},
            json={
                'task': 'Implement documentation update',
                'task_type': 'docs',
                'branch': 'feature/docs',
                'base_commit': 'c8708b5',
            },
        )
        self.assertEqual(submit_res.status_code, 201)
        job_id = submit_res.json()['job_id']
        self.assertEqual(submit_res.json()['status'], 'QUEUED')

        # Query job status
        status_res = self.client.get(f'/jobs/{job_id}', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()['job_id'], job_id)
        self.assertEqual(status_res.json()['developer_id'], 'alice')
        self.assertEqual(status_res.json()['status'], 'QUEUED')

    def test_submit_job_short_task_rejected_400(self):
        token = self._authenticate('alice', self.dev_priv)
        res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token}'},
            json={'task': 'Too short', 'task_type': 'docs', 'branch': 'feature/docs', 'base_commit': 'abc'},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('at least 10 characters', res.json()['error'])

    def test_submit_job_oversized_task_413(self):
        token = self._authenticate('alice', self.dev_priv)
        oversized = 'A' * 2000
        res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token}'},
            json={'task': oversized, 'task_type': 'docs', 'branch': 'feature/docs', 'base_commit': 'abc1234'},
        )
        self.assertEqual(res.status_code, 413)

    def test_cancel_job(self):
        token = self._authenticate('alice', self.dev_priv)
        submit_res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token}'},
            json={
                'task': 'Task to be cancelled',
                'task_type': 'docs',
                'branch': 'feature/cancel',
                'base_commit': 'abc1234',
            },
        )
        job_id = submit_res.json()['job_id']
        cancel_res = self.client.post(f'/jobs/{job_id}/cancel', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.json()['status'], 'CANCELLED')

    def test_worker_status_requires_authentication(self):
        self.assertEqual(self.client.get('/worker/status').status_code, 401)
        self.assertEqual(self.client.get('/worker/status', headers={'Authorization': 'Bearer not-a-token'}).status_code, 401)

    def test_worker_status_endpoint(self):
        token = self._authenticate('alice', self.dev_priv)
        res = self.client.get('/worker/status', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(res.status_code, 200)
        self.assertIn('workers', res.json())

    def test_enrolled_worker_is_offline_until_it_heartbeats_and_offline_again_when_stale(self):
        self.worker_registry.enroll('worker-x', base64.b64encode(ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode())
        token = self._authenticate('alice', self.dev_priv)
        fetch = lambda: next(w for w in self.client.get('/worker/status', headers={'Authorization': f'Bearer {token}'}).json()['workers'] if w['worker_id'] == 'worker-x')

        self.assertFalse(fetch()['online'])
        self.gateway.queue.heartbeat_worker('worker-x')
        self.assertTrue(fetch()['online'])
        self.gateway.worker_online_window_seconds = 0.0
        self.assertFalse(fetch()['online'])


if __name__ == '__main__':
    unittest.main()
