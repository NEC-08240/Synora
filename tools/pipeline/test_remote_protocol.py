# Tests for Protocol Envelopes and Remote MCP Client Protocol
import base64
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .protocol import (
    MSG_AUTHENTICATE,
    MSG_HEARTBEAT,
    MSG_JOB_ACK,
    MSG_JOB_ASSIGN,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_WORKER_REGISTER,
    ProtocolEnvelope,
    ProtocolError,
)
from .remote_shim import RemoteGatewayClient
from .team_registry import DeveloperEntry, TeamRegistry


class TestRemoteProtocol(unittest.TestCase):
    def setUp(self):
        self.registry = TeamRegistry()
        self.dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(self.dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub)
        self.registry.register(self.dev)

        self.gateway = Gateway(registry=self.registry)
        self.app = create_gateway_app(self.gateway)
        self.tc = TestClient(self.app)

        self.client = RemoteGatewayClient(
            gateway_url='http://testserver',
            developer_id='alice',
            private_key=self.dev_priv,
            custom_client=self.tc,
        )

    def tearDown(self):
        self.gateway.queue.close()

    def test_protocol_envelope_roundtrip(self):
        msg = ProtocolEnvelope(
            message_type=MSG_JOB_ASSIGN,
            sender_id='gateway-1',
            payload={'job_id': 'job-proto-1'},
        )
        serialized = msg.serialize()
        parsed = ProtocolEnvelope.parse(serialized)
        self.assertEqual(parsed.message_type, MSG_JOB_ASSIGN)
        self.assertEqual(parsed.sender_id, 'gateway-1')
        self.assertEqual(parsed.payload['job_id'], 'job-proto-1')

    def test_unknown_message_type_rejected(self):
        with self.assertRaises(ProtocolError):
            ProtocolEnvelope(
                message_type='INVALID_TYPE_XYZ',
                sender_id='sender-1',
                payload={},
            )

    def test_missing_required_payload_fields_rejected(self):
        # MSG_JOB_RESULT requires ('job_id', 'status')
        with self.assertRaises(ProtocolError):
            ProtocolEnvelope(
                message_type=MSG_JOB_RESULT,
                sender_id='worker-1',
                payload={'job_id': 'job-123'},  # missing 'status'
            )

    def test_malformed_json_rejected(self):
        with self.assertRaises(ProtocolError):
            ProtocolEnvelope.parse('{invalid json string')

    def test_remote_client_full_lifecycle(self):
        # Authenticate
        token = self.client.authenticate()
        self.assertTrue(len(token) > 0)
        self.assertEqual(self.client.token, token)

        # Submit task
        sub = self.client.submit_task(
            task='Test remote client submission',
            task_type='docs',
            branch='feature/test-remote',
            base_commit='abc1234',
        )
        self.assertTrue(sub.get('success'))
        job_id = sub['job_id']

        # Get status
        status = self.client.get_status(job_id)
        self.assertEqual(status['status'], 'QUEUED')
        self.assertEqual(status['job_id'], job_id)

        # Cancel job
        cancel_res = self.client.cancel_job(job_id)
        self.assertTrue(cancel_res.get('success'))

        # Get status after cancel
        status_after = self.client.get_status(job_id)
        self.assertEqual(status_after['status'], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
