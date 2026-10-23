# Tests for LAN Mode and TLS Enforcement (Milestone G, Section 23 & 15)
import base64
import os
import ssl
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .team_registry import DeveloperEntry, TeamRegistry
from .tls_config import (
    create_client_ssl_context,
    create_server_ssl_context,
    generate_ephemeral_test_cert,
)


class TestLANMode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cert_path, self.key_path = generate_ephemeral_test_cert(
            self.temp_dir.name,
            common_name='localhost',
            ip_addresses=['127.0.0.1', '192.168.1.50'],
        )

        self.registry = TeamRegistry()
        self.alice_priv = ed25519.Ed25519PrivateKey.generate()
        alice_pub = base64.b64encode(self.alice_priv.public_key().public_bytes_raw()).decode()
        self.alice = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=alice_pub)
        self.registry.register(self.alice)

        self.bob_priv = ed25519.Ed25519PrivateKey.generate()
        bob_pub = base64.b64encode(self.bob_priv.public_key().public_bytes_raw()).decode()
        self.bob = DeveloperEntry('bob', 'Bob', 'bob-gh', 'developer', 'active', public_key_ed25519=bob_pub)
        self.registry.register(self.bob)

        self.gateway = Gateway(registry=self.registry)
        self.app = create_gateway_app(self.gateway)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.gateway.queue.close()
        self.temp_dir.cleanup()

    def test_server_tls_configuration_enforces_modern_standards(self):
        server_ctx = create_server_ssl_context(self.cert_path, self.key_path)
        # Enforce minimum TLS 1.2
        self.assertGreaterEqual(server_ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        # Verify cipher preference option
        self.assertTrue(server_ctx.options & ssl.OP_CIPHER_SERVER_PREFERENCE)

    def test_client_tls_enforces_certificate_validation_no_verify_false(self):
        client_ctx = create_client_ssl_context(ca_certfile=self.cert_path, check_hostname=True)
        # Invariant: verify_mode must be CERT_REQUIRED, never CERT_NONE
        self.assertEqual(client_ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(client_ctx.check_hostname)

    def test_lan_unauthenticated_access_rejected(self):
        # Even on LAN, all endpoints require challenge-response authentication.
        # Direct unauthenticated access to /jobs is rejected with 401
        res = self.client.post('/jobs', json={'task': 'LAN task without auth'})
        self.assertEqual(res.status_code, 401)
        self.assertIn('Missing Authorization header', res.json()['error'])

    def test_lan_authenticated_job_flow_and_isolation(self):
        # Alice authenticates over LAN
        c_res = self.client.post('/auth/challenge', json={'developer_id': 'alice'}).json()
        sig = base64.b64encode(self.alice_priv.sign(c_res['message'].encode())).decode()
        token_alice = self.client.post(
            '/auth/verify',
            json={'developer_id': 'alice', 'nonce': c_res['nonce'], 'signature': sig},
        ).json()['token']

        # Alice submits job
        sub = self.client.post(
            '/jobs',
            headers={'Authorization': f'Bearer {token_alice}'},
            json={
                'task': 'Documentation update on local LAN',
                'task_type': 'docs',
                'branch': 'feature/lan-doc',
                'base_commit': 'abc1234',
            },
        )
        self.assertEqual(sub.status_code, 201)
        job_id = sub.json()['job_id']

        # Bob authenticates over LAN
        c_bob = self.client.post('/auth/challenge', json={'developer_id': 'bob'}).json()
        sig_bob = base64.b64encode(self.bob_priv.sign(c_bob['message'].encode())).decode()
        token_bob = self.client.post(
            '/auth/verify',
            json={'developer_id': 'bob', 'nonce': c_bob['nonce'], 'signature': sig_bob},
        ).json()['token']

        # Bob on LAN is REJECTED from reading Alice's job (cross-developer isolation preserved)
        cross_res = self.client.get(f'/jobs/{job_id}', headers={'Authorization': f'Bearer {token_bob}'})
        self.assertEqual(cross_res.status_code, 403)


if __name__ == '__main__':
    unittest.main()
