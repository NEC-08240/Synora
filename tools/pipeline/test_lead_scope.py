"""The authorized scope must travel with the job, so the Worker can enforce it without trusting teammate text.

Covers the queue (new column, claim payload), the Gateway (scope is taken from the authenticated developer's
registry entry, never from the request body), and an existing database without the new column (migrated).
Run: python -m unittest tools.pipeline.test_lead_scope -v
"""

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519
from starlette.testclient import TestClient

from .gateway import Gateway
from .gateway_app import create_gateway_app
from .queue import JobQueue
from .team_registry import DeveloperEntry, TeamRegistry


def _job(job_id, scope=None):
    job = {"job_id": job_id, "developer_id": "alice", "task": "Update the frontend notes.", "task_type": "docs",
           "branch": "feature/fe-1", "base_commit": "abc1234"}
    if scope is not None:
        job["scope"] = scope
    return job


class QueueScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "gateway.db")
        self.queue = JobQueue(self.db)

    def tearDown(self):
        self.queue.close()
        self._tmp.cleanup()

    def test_scope_is_returned_with_the_claimed_job(self):
        scope = {"modules": ["frontend/*"], "branches": ["feature/fe-*"]}
        self.queue.enqueue(_job("job-1", scope))
        claimed = self.queue.claim_next("worker-a")
        self.assertEqual(claimed["scope"], scope)

    def test_job_without_scope_claims_with_none(self):
        self.queue.enqueue(_job("job-2"))
        self.assertIsNone(self.queue.claim_next("worker-a")["scope"])

    def test_existing_database_without_the_column_is_migrated(self):
        legacy = str(Path(self._tmp.name) / "legacy.db")
        conn = sqlite3.connect(legacy)
        conn.execute(
            "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, developer_id TEXT NOT NULL, task TEXT NOT NULL, "
            "task_type TEXT NOT NULL, branch TEXT NOT NULL, base_commit TEXT NOT NULL, diff TEXT NOT NULL, "
            "is_repair INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, worker_id TEXT, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, assigned_at TEXT, finished_at TEXT, result_json TEXT, error TEXT);"
        )
        conn.execute(
            "INSERT INTO jobs (job_id, developer_id, task, task_type, branch, base_commit, diff, status, created_at, updated_at) "
            "VALUES ('old-1', 'alice', 'Old job text here.', 'docs', 'feature/fe-1', 'abc1234', '', 'QUEUED', 'x', 'x');"
        )
        conn.commit()
        conn.close()
        migrated = JobQueue(legacy)
        try:
            self.assertIsNone(migrated.get_job("old-1").get("scope"))
            migrated.enqueue(_job("new-1", {"modules": ["docs/"], "branches": ["feature/x/*"]}))
        finally:
            migrated.close()


class GatewayScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.priv = ed25519.Ed25519PrivateKey.generate()
        pub = base64.b64encode(self.priv.public_key().public_bytes_raw()).decode()
        self.registry = TeamRegistry()
        self.registry.register(DeveloperEntry(
            developer_id="alice", developer_name="Alice", github_username="alice-gh", role="developer",
            status="active", public_key_ed25519=pub, assigned_modules=("frontend/*",), allowed_branches=("feature/fe-*",),
        ))
        self.gateway = Gateway(registry=self.registry, queue=JobQueue(str(Path(self._tmp.name) / "g.db")))
        self.client = TestClient(create_gateway_app(self.gateway))

    def tearDown(self):
        self.gateway.queue.close()
        self._tmp.cleanup()

    def _token(self):
        c = self.client.post("/auth/challenge", json={"developer_id": "alice"}).json()
        sig = base64.b64encode(self.priv.sign(c["message"].encode())).decode()
        return self.client.post("/auth/verify", json={"developer_id": "alice", "nonce": c["nonce"], "signature": sig}).json()["token"]

    def test_scope_comes_from_the_registry_not_the_request(self):
        token = self._token()
        res = self.client.post(
            "/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"task": "Update the frontend notes.", "task_type": "docs", "branch": "feature/fe-1",
                  "base_commit": "abc1234", "scope": {"modules": ["/"], "branches": ["*"]}},
        )
        self.assertEqual(res.status_code, 201, res.text)
        claimed = self.gateway.queue.claim_next("worker-a")
        # The registry normalizes module scopes to a trailing-slash prefix; the scope must equal that normalized form.
        expected_modules = list(self.registry.get("alice").assigned_modules)
        self.assertEqual(claimed["scope"], {"modules": expected_modules, "branches": ["feature/fe-*"]})


if __name__ == "__main__":
    unittest.main()
