# Tests for Gateway Authentication
import base64
import time
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519

from .audit import AuditLogger
from .auth import (
    AuthenticationError,
    ChallengeExpired,
    DeveloperSuspended,
    ReplayDetected,
    create_session_token,
    verify_session_token,
)
from .gateway import Gateway
from .team_registry import DeveloperEntry, TeamRegistry


class TestGatewayAuth(unittest.TestCase):
    def setUp(self):
        self.registry = TeamRegistry()
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

        self.audit = AuditLogger()
        self.gateway = Gateway(registry=self.registry, audit=self.audit)

    def tearDown(self):
        self.gateway.queue.close()

    def test_full_challenge_verify_success(self):
        challenge = self.gateway.request_challenge('alice')
        self.assertIn('nonce', challenge)
        self.assertIn('message', challenge)

        sig_raw = self.dev_priv.sign(challenge['message'].encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')

        token = self.gateway.authenticate('alice', challenge['nonce'], sig_b64)
        self.assertTrue(len(token) > 0)

        caller = self.gateway.verify_caller(token)
        self.assertEqual(caller.developer_id, 'alice')

    def test_replayed_nonce_rejected(self):
        challenge = self.gateway.request_challenge('alice')
        sig_raw = self.dev_priv.sign(challenge['message'].encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')

        # First use succeeds
        self.gateway.authenticate('alice', challenge['nonce'], sig_b64)

        # Replay attempt fails
        with self.assertRaises(ReplayDetected):
            self.gateway.authenticate('alice', challenge['nonce'], sig_b64)

    def test_expired_challenge_rejected(self):
        self.gateway.challenges.default_ttl = -1.0  # Force immediate expiration
        challenge = self.gateway.request_challenge('alice')
        sig_raw = self.dev_priv.sign(challenge['message'].encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')

        with self.assertRaises(ChallengeExpired):
            self.gateway.authenticate('alice', challenge['nonce'], sig_b64)

    def test_suspended_developer_rejected(self):
        self.registry.suspend('alice')
        with self.assertRaises(AuthenticationError):
            self.gateway.request_challenge('alice')

    def test_tampered_session_token_rejected(self):
        challenge = self.gateway.request_challenge('alice')
        sig_raw = self.dev_priv.sign(challenge['message'].encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')
        token = self.gateway.authenticate('alice', challenge['nonce'], sig_b64)

        # Tamper payload
        parts = token.split('.')
        tampered_token = f'tampered_{parts[0]}.{parts[1]}'
        with self.assertRaises(AuthenticationError):
            self.gateway.verify_caller(tampered_token)

    def test_expired_session_token_rejected(self):
        token = create_session_token(self.dev, self.gateway.signing_secret, ttl_seconds=-10)
        with self.assertRaises(AuthenticationError):
            verify_session_token(token, self.gateway.signing_secret, self.registry)

    def test_session_token_is_ip_agnostic(self):
        token = create_session_token(self.dev, self.gateway.signing_secret, ttl_seconds=3600)
        verified_dev = verify_session_token(token, self.gateway.signing_secret, self.registry)
        self.assertEqual(verified_dev.developer_id, 'alice')

    def test_audit_scrubbing_of_secrets(self):
        challenge = self.gateway.request_challenge('alice')
        sig_raw = self.dev_priv.sign(challenge['message'].encode('utf-8'))
        sig_b64 = base64.b64encode(sig_raw).decode('ascii')
        self.gateway.authenticate('alice', challenge['nonce'], sig_b64)

        logs = self.audit.events()
        for log in logs:
            log_str = str(log)
            self.assertNotIn(sig_b64, log_str)


if __name__ == '__main__':
    unittest.main()
