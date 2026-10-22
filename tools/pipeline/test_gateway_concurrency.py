# Tests for Gateway Concurrency, Queue Limits, Fair Scheduling, and Crash Recovery
import base64
import os
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric import ed25519

from .gateway import Gateway
from .queue import JobQueue, QueueFullError, RateLimitExceeded
from .team_registry import DeveloperEntry, TeamRegistry


class TestGatewayConcurrency(unittest.TestCase):
    def setUp(self):
        self.registry = TeamRegistry()

        # Alice
        self.alice_priv = ed25519.Ed25519PrivateKey.generate()
        alice_pub = base64.b64encode(self.alice_priv.public_key().public_bytes_raw()).decode()
        self.alice = DeveloperEntry('alice', 'Alice', 'alice-gh', 'developer', 'active', public_key_ed25519=alice_pub)
        self.registry.register(self.alice)

        # Bob
        self.bob_priv = ed25519.Ed25519PrivateKey.generate()
        bob_pub = base64.b64encode(self.bob_priv.public_key().public_bytes_raw()).decode()
        self.bob = DeveloperEntry('bob', 'Bob', 'bob-gh', 'developer', 'active', public_key_ed25519=bob_pub)
        self.registry.register(self.bob)

    def test_per_developer_concurrency_limit(self):
        queue = JobQueue(':memory:', max_depth=10)
        gateway = Gateway(registry=self.registry, queue=queue, max_jobs_per_developer=1)

        # Alice authenticates and submits job 1
        c = gateway.request_challenge('alice')
        sig = base64.b64encode(self.alice_priv.sign(c['message'].encode())).decode()
        token = gateway.authenticate('alice', c['nonce'], sig)

        res1 = gateway.submit_job(token, {
            'task': 'First valid active task',
            'task_type': 'docs',
            'branch': 'feature/alice-1',
            'base_commit': 'abc1234',
        })
        self.assertTrue(res1['success'])

        # Alice submits job 2 while job 1 is still active -> RateLimitExceeded
        with self.assertRaises(RateLimitExceeded):
            gateway.submit_job(token, {
                'task': 'Second concurrent task that should be rejected',
                'task_type': 'docs',
                'branch': 'feature/alice-2',
                'base_commit': 'abc1234',
            })

        # Cancel job 1
        gateway.cancel_job(token, res1['job_id'])

        # Now Alice can submit job 2 successfully
        res2 = gateway.submit_job(token, {
            'task': 'Second task after first was cancelled',
            'task_type': 'docs',
            'branch': 'feature/alice-2',
            'base_commit': 'abc1234',
        })
        self.assertTrue(res2['success'])
        queue.close()

    def test_queue_depth_limit(self):
        queue = JobQueue(':memory:', max_depth=2)
        gateway = Gateway(registry=self.registry, queue=queue, max_jobs_per_developer=10)

        c_a = gateway.request_challenge('alice')
        sig_a = base64.b64encode(self.alice_priv.sign(c_a['message'].encode())).decode()
        token_a = gateway.authenticate('alice', c_a['nonce'], sig_a)

        gateway.submit_job(token_a, {'task': 'Task one for queue depth', 'task_type': 'docs', 'branch': 'f/1', 'base_commit': 'abc1234'})
        gateway.submit_job(token_a, {'task': 'Task two for queue depth', 'task_type': 'docs', 'branch': 'f/2', 'base_commit': 'abc1234'})

        # Third job exceeds max_depth of 2
        with self.assertRaises(QueueFullError):
            gateway.submit_job(token_a, {'task': 'Task three exceeding limit', 'task_type': 'docs', 'branch': 'f/3', 'base_commit': 'abc1234'})

        queue.close()

    def test_concurrent_worker_claim_is_atomic(self):
        queue = JobQueue(':memory:')
        gateway = Gateway(registry=self.registry, queue=queue)

        c = gateway.request_challenge('alice')
        sig = base64.b64encode(self.alice_priv.sign(c['message'].encode())).decode()
        token = gateway.authenticate('alice', c['nonce'], sig)
        gateway.submit_job(token, {'task': 'Single job to claim atomically', 'task_type': 'docs', 'branch': 'f/1', 'base_commit': 'abc1234'})

        # Worker 1 claims job
        claim1 = queue.claim_next('worker-1')
        self.assertIsNotNone(claim1)
        self.assertEqual(claim1['worker_id'], 'worker-1')

        # Worker 2 attempts to claim the same queue -> returns None (nothing to claim)
        claim2 = queue.claim_next('worker-2')
        self.assertIsNone(claim2)

        queue.close()

    def test_fair_scheduling_interleaves_developers(self):
        queue = JobQueue(':memory:')
        # Alice enqueues 2 jobs, Bob enqueues 1 job
        queue.enqueue({'job_id': 'a1', 'developer_id': 'alice', 'task': 'Task A1', 'task_type': 'docs'})
        queue.enqueue({'job_id': 'a2', 'developer_id': 'alice', 'task': 'Task A2', 'task_type': 'docs'})
        queue.enqueue({'job_id': 'b1', 'developer_id': 'bob', 'task': 'Task B1', 'task_type': 'docs'})

        # Claim 1: Alice has 0 active, Bob has 0 active -> oldest is a1
        c1 = queue.claim_next('worker-1')
        self.assertEqual(c1['job_id'], 'a1')

        # Claim 2: Alice now has 1 active (a1 is ASSIGNED). Bob has 0 active -> Bob is prioritized!
        c2 = queue.claim_next('worker-2')
        self.assertEqual(c2['job_id'], 'b1')

        # Claim 3: Bob has 1 active, Alice has 1 active -> oldest remaining is a2
        c3 = queue.claim_next('worker-3')
        self.assertEqual(c3['job_id'], 'a2')

        queue.close()

    def test_crash_and_restart_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'persistent_queue.db')

            # Instance 1: start, enqueue job, crash (close)
            q1 = JobQueue(db_path)
            q1.enqueue({'job_id': 'job-recover-1', 'developer_id': 'alice', 'task': 'Task surviving crash', 'task_type': 'docs'})
            q1.close()

            # Instance 2: restart from same sqlite DB
            q2 = JobQueue(db_path)
            job = q2.get_job('job-recover-1')
            self.assertIsNotNone(job)
            self.assertEqual(job['status'], 'QUEUED')
            self.assertEqual(job['task'], 'Task surviving crash')

            # Claim and finish
            claim = q2.claim_next('worker-restart-1')
            self.assertEqual(claim['job_id'], 'job-recover-1')
            q2.close()


if __name__ == '__main__':
    unittest.main()
