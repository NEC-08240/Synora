# Tests for Gateway Authorization Policy (Milestone B)
import base64
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .authorization import AuthorizationError
from .gateway import Gateway
from .gateway_app import create_gateway_app
from .team_registry import DeveloperEntry, TeamRegistry


class TestGatewayAuthorization(unittest.TestCase):
    def setUp(self):
        self.registry = TeamRegistry()

        # Developer Alice (assigned to frontend/*, branches feature/fe-*)
        self.alice_priv = ed25519.Ed25519PrivateKey.generate()
        alice_pub = base64.b64encode(self.alice_priv.public_key().public_bytes_raw()).decode()
        self.alice = DeveloperEntry(
            developer_id='alice',
            developer_name='Alice Frontend',
            github_username='alice-gh',
            role='developer',
            status='active',
            public_key_ed25519=alice_pub,
            assigned_modules=('frontend/*',),
            allowed_branches=('feature/fe-*',),
        )
        self.registry.register(self.alice)

        # Developer Bob (assigned to backend/*, branches feature/be-*)
        self.bob_priv = ed25519.Ed25519PrivateKey.generate()
        bob_pub = base64.b64encode(self.bob_priv.public_key().public_bytes_raw()).decode()
        self.bob = DeveloperEntry(
            developer_id='bob',
            developer_name='Bob Backend',
            github_username='bob-gh',
            role='developer',
            status='active',
            public_key_ed25519=bob_pub,
            assigned_modules=('backend/*',),
            allowed_branches=('feature/be-*',),
        )
        self.registry.register(self.bob)

        # Project Owner Johan
        self.johan_priv = ed25519.Ed25519PrivateKey.generate()
        johan_pub = base64.b64encode(self.johan_priv.public_key().public_bytes_raw()).decode()
        self.johan = DeveloperEntry(
            developer_id='johan',
            developer_name='Johan Owner',
            github_username='johan-gh',
            role='project_owner',
            status='active',
            public_key_ed25519=johan_pub,
            assigned_modules=('*',),
            allowed_branches=('*',),
        )
        self.registry.register(self.johan)

        self.gateway = Gateway(registry=self.registry)
        self.app = create_gateway_app(self.gateway)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.gateway.queue.close()

    def _auth(self, dev_id: str, priv_key: ed25519.Ed25519PrivateKey) -> str:
        c = self.client.post('/auth/challenge', json={'developer_id': dev_id}).json()
        sig = base64.b64encode(priv_key.sign(c['message'].encode())).decode()
        return self.client.post(
            '/auth/verify',
            json={'developer_id': dev_id, 'nonce': c['nonce'], 'signature': sig},
        ).json()['token']

    def test_identity_spoofing_in_payload_rejected(self):
        # Alice is authenticated, but claims developer_id='bob' in JSON body
        token_alice = self._auth('alice', self.alice_priv)
        res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token_alice}'},
            json={
                'developer_id': 'bob',
                'task': 'Malicious spoof attempt',
                'task_type': 'docs',
                'branch': 'feature/fe-1',
                'base_commit': 'abc1234',
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('does not match authenticated identity', res.json()['error'])

    def test_unauthorized_branch_rejected(self):
        # Alice attempts to submit to Bob's branch pattern feature/be-1
        token_alice = self._auth('alice', self.alice_priv)
        res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token_alice}'},
            json={
                'task': 'Unauthorized branch task',
                'task_type': 'docs',
                'branch': 'feature/be-1',
                'base_commit': 'abc1234',
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('not authorized for branch', res.json()['error'])

    def test_cross_developer_job_isolation(self):
        # Alice creates a job
        token_alice = self._auth('alice', self.alice_priv)
        sub_res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token_alice}'},
            json={
                'task': 'Alice private feature documentation',
                'task_type': 'docs',
                'branch': 'feature/fe-test',
                'base_commit': 'abc1234',
            },
        )
        job_id = sub_res.json()['job_id']

        # Bob attempts to read Alice's job status -> 403 Forbidden
        token_bob = self._auth('bob', self.bob_priv)
        status_res = self.client.get(
            f'/jobs/{job_id}',
            headers={'Authorization': f'Bearer {token_bob}'},
        )
        self.assertEqual(status_res.status_code, 403)

        # Bob attempts to read Alice's job result -> 403 Forbidden
        result_res = self.client.get(
            f'/jobs/{job_id}/result',
            headers={'Authorization': f'Bearer {token_bob}'},
        )
        self.assertEqual(result_res.status_code, 403)

        # Bob attempts to cancel Alice's job -> 400/403
        cancel_res = self.client.post(
            f'/jobs/{job_id}/cancel',
            headers={'Authorization': f'Bearer {token_bob}'},
        )
        self.assertIn(cancel_res.status_code, (400, 403))

    def test_project_owner_bypasses_job_isolation(self):
        # Alice creates a job
        token_alice = self._auth('alice', self.alice_priv)
        sub_res = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token_alice}'},
            json={
                'task': 'Alice private feature documentation',
                'task_type': 'docs',
                'branch': 'feature/fe-test',
                'base_commit': 'abc1234',
            },
        )
        job_id = sub_res.json()['job_id']

        # Johan (project owner) can view and cancel any job
        token_johan = self._auth('johan', self.johan_priv)
        status_res = self.client.get(
            f'/jobs/{job_id}',
            headers={'Authorization': f'Bearer {token_johan}'},
        )
        self.assertEqual(status_res.status_code, 200)

        cancel_res = self.client.post(
            f'/jobs/{job_id}/cancel',
            headers={'Authorization': f'Bearer {token_johan}'},
        )
        self.assertEqual(cancel_res.status_code, 200)


if __name__ == '__main__':
    unittest.main()
