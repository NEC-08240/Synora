# Tests for Signed Result Envelopes (Milestone F)
import base64
import time
import unittest
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric import ed25519

from .gateway import Gateway
from .queue import JobQueue
from .result_envelope import (
    InvalidResultSignature,
    ResultEnvelope,
    ResultEnvelopeError,
    ResultExpired,
    ResultMismatchError,
    ResultReplayDetected,
    canonical_serialize,
)
from .team_registry import DeveloperEntry, TeamRegistry
from .worker_registry import WorkerRegistry


class TestResultSigning(unittest.TestCase):
    def setUp(self):
        self.worker_priv = ed25519.Ed25519PrivateKey.generate()
        self.worker_pub = self.worker_priv.public_key()
        self.worker_pub_b64 = base64.b64encode(self.worker_pub.public_bytes_raw()).decode()

        self.worker_registry = WorkerRegistry()
        self.worker_registry.enroll('worker-1', self.worker_pub_b64)

        self.registry = TeamRegistry()
        dev_priv = ed25519.Ed25519PrivateKey.generate()
        dev_pub = base64.b64encode(dev_priv.public_key().public_bytes_raw()).decode()
        self.dev = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=dev_pub)
        self.registry.register(self.dev)

        self.queue = JobQueue(':memory:')
        self.gateway = Gateway(
            registry=self.registry,
            queue=self.queue,
            worker_registry=self.worker_registry,
            max_result_age_seconds=60.0,
        )

        # Enqueue and claim a test job
        self.queue.enqueue({'job_id': 'job-sig-1', 'developer_id': 'alice', 'task': 'Task signing test', 'task_type': 'docs'})
        self.claimed_job = self.queue.claim_next('worker-1')

    def tearDown(self):
        self.queue.close()

    def test_canonical_serialization_determinism(self):
        payload1 = {
            'job_id': 'job-1',
            'developer_id': 'alice',
            'worker_id': 'worker-1',
            'attempt': 1,
            'status': 'SUCCEEDED',
            'result': {'b': 2, 'a': 1},
            'timestamp': '2026-10-22T12:00:00Z',
            'nonce': '1234567890abcdef',
        }
        # Inverted key order in result and payload
        payload2 = {
            'nonce': '1234567890abcdef',
            'timestamp': '2026-10-22T12:00:00Z',
            'result': {'a': 1, 'b': 2},
            'status': 'SUCCEEDED',
            'attempt': 1,
            'worker_id': 'worker-1',
            'developer_id': 'alice',
            'job_id': 'job-1',
        }
        bytes1 = canonical_serialize(payload1)
        bytes2 = canonical_serialize(payload2)
        self.assertEqual(bytes1, bytes2)

    def test_valid_signed_result_accepted(self):
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-1',
            status='SUCCEEDED',
            result={'verified': True, 'output': 'Code verified perfectly'},
        )
        res = self.gateway.worker_submit_signed_result(envelope)
        self.assertTrue(res['success'])
        self.assertEqual(res['status'], 'SUCCEEDED')

        # Check job in queue
        job = self.queue.get_job('job-sig-1')
        self.assertEqual(job['status'], 'SUCCEEDED')
        self.assertTrue(job['result']['verified'])

    def test_tampered_payload_rejected(self):
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-1',
            status='FAILED',
            result={'error': 'Tests failed'},
        )
        # Malicious actor tampers status from FAILED to SUCCEEDED
        envelope['status'] = 'SUCCEEDED'
        with self.assertRaises(InvalidResultSignature):
            self.gateway.worker_submit_signed_result(envelope)

    def test_tampered_signature_rejected(self):
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-1',
            status='SUCCEEDED',
            result={'output': 'done'},
        )
        envelope['signature'] = base64.b64encode(b'bad_signature_bytes_32_bytes_pad!').decode()
        with self.assertRaises(InvalidResultSignature):
            self.gateway.worker_submit_signed_result(envelope)

    def test_expired_result_rejected(self):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-1',
            status='SUCCEEDED',
            result={'output': 'done'},
            timestamp=old_time,
        )
        with self.assertRaises(ResultExpired):
            self.gateway.worker_submit_signed_result(envelope)

    def test_replay_nonce_rejected(self):
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-1',
            status='SUCCEEDED',
            result={'output': 'done'},
        )
        # First submission succeeds
        self.gateway.worker_submit_signed_result(envelope)

        # Replayed envelope with identical nonce rejected
        with self.assertRaises(ResultReplayDetected):
            self.gateway.worker_submit_signed_result(envelope)

    def test_worker_mismatch_rejected(self):
        # Worker 2 was not assigned the job
        w2_priv = ed25519.Ed25519PrivateKey.generate()
        w2_pub = base64.b64encode(w2_priv.public_key().public_bytes_raw()).decode()
        self.worker_registry.enroll('worker-2', w2_pub)

        envelope = ResultEnvelope.create(
            private_key=w2_priv,
            job_id='job-sig-1',
            developer_id='alice',
            worker_id='worker-2',
            status='SUCCEEDED',
            result={'output': 'done'},
        )
        with self.assertRaises(ResultMismatchError):
            self.gateway.worker_submit_signed_result(envelope)

    def test_developer_mismatch_rejected(self):
        envelope = ResultEnvelope.create(
            private_key=self.worker_priv,
            job_id='job-sig-1',
            developer_id='bob',  # Job was for alice!
            worker_id='worker-1',
            status='SUCCEEDED',
            result={'output': 'done'},
        )
        with self.assertRaises(ResultMismatchError):
            self.gateway.worker_submit_signed_result(envelope)


if __name__ == '__main__':
    unittest.main()
