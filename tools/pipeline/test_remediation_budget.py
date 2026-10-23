"""F3: Worker-local budget. Run: python -m unittest tools.pipeline.test_remediation_budget -v

A hostile Gateway can queue unlimited jobs. These tests drive the real Worker job path against a real
git repository and count the Claude calls that actually happen. Only the Claude process is replaced.
"""

import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from . import budget as budget_module
from .bridge import IMPLEMENT_TOOLS, Bridge
from .budget import BudgetExceeded, WorkerBudget
from .worker import ClaudeWorker


class CountingClaude:
    def __init__(self):
        self.implement_calls = 0

    def __call__(self, prompt, cwd, tools, permission_mode):
        if tools == IMPLEMENT_TOOLS:
            self.implement_calls += 1
            target = Path(cwd) / "docs" / "agent-bridge" / f"doc-{uuid.uuid4().hex[:8]}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# doc\n", encoding="utf-8")
            result = "wrote a doc"
        else:
            result = '{"verdict": "PASS", "findings": []}'
        return 0, json.dumps({"subtype": "success", "is_error": False, "result": result}), ""


class FakeGateway:
    """Hostile Gateway: it hands out whatever jobs it likes and records every failure report."""

    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.results = []
        self.failures = []

    def worker_poll_job(self, worker_id):
        return self.jobs.pop(0) if self.jobs else None

    def worker_submit_signed_result(self, envelope):
        self.results.append(envelope)

    def worker_submit_failure(self, worker_id, job_id, message):
        self.failures.append((job_id, message))


def _job(**extra):
    return {"job_id": str(uuid.uuid4()), "developer_id": "alice", "task": "Write a doc.", "task_type": "docs", **extra}


class BudgetTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "i"], cwd=self.repo, check=True)
        self.claude = CountingClaude()
        self.bridge = Bridge(repo_root=self.repo, runner=self.claude)
        self.state_dir = self.bridge.records_dir.parent
        self.clock = [1000.0]

    def tearDown(self):
        self._tmp.cleanup()

    def _worker(self, gateway, **budget_kwargs):
        budget = WorkerBudget(self.state_dir, clock=lambda: self.clock[0], **budget_kwargs)
        return ClaudeWorker("worker-test", bridge=self.bridge, gateway=gateway, budget=budget), budget


class RateLimitTest(BudgetTestCase):
    def test_f3_1_queued_jobs_beyond_the_local_limit_never_reach_claude(self):
        gateway = FakeGateway([_job() for _ in range(10)])
        worker, _ = self._worker(gateway, jobs_per_window=3, window_seconds=3600)

        for _ in range(10):
            worker.process_one_job()

        self.assertEqual(self.claude.implement_calls, 3)
        self.assertEqual(len(gateway.failures), 7)
        self.assertTrue(all("Rate limit" in message for _, message in gateway.failures))

    def test_f3_2_remote_budget_fields_are_ignored(self):
        hostile = _job(max_jobs=999999, budget="unlimited", rate_limit=0, disk_limit=0, jobs_per_window=10**9)
        gateway = FakeGateway([hostile] * 5)
        worker, budget = self._worker(gateway, jobs_per_window=2)

        for _ in range(5):
            worker.process_one_job()

        self.assertEqual(self.claude.implement_calls, 2)
        self.assertEqual(budget.jobs_per_window, 2)

    def test_f3_3_gateway_cannot_reset_the_counter(self):
        gateway = FakeGateway([_job(reset_budget=True, clear_counter=True)] * 4)
        worker, _ = self._worker(gateway, jobs_per_window=2)
        for _ in range(4):
            worker.process_one_job()
        self.assertEqual(self.claude.implement_calls, 2)

        restarted = WorkerBudget(self.state_dir, jobs_per_window=2, clock=lambda: self.clock[0])
        with self.assertRaises(BudgetExceeded):
            restarted.admit()

    def test_f3_4_the_window_recovers_when_time_passes(self):
        budget = WorkerBudget(self.state_dir, jobs_per_window=1, window_seconds=60, clock=lambda: self.clock[0])
        budget.admit()
        budget.finish()
        with self.assertRaises(BudgetExceeded):
            budget.admit()

        self.clock[0] += 61
        budget.admit()
        budget.finish()

    def test_counts_are_written_before_the_job_runs(self):
        budget = WorkerBudget(self.state_dir, jobs_per_window=5, clock=lambda: self.clock[0])
        budget.admit()
        stamps = json.loads((self.state_dir / "worker_budget.json").read_text(encoding="utf-8"))["starts"]

        self.assertEqual(len(stamps), 1)
        budget.finish()


class ConcurrencyAndDiskTest(BudgetTestCase):
    def test_f3_concurrency_second_job_refused_while_one_runs(self):
        budget = WorkerBudget(self.state_dir, jobs_per_window=5, clock=lambda: self.clock[0])
        budget.admit()
        with self.assertRaises(BudgetExceeded):
            budget.admit()
        budget.finish()
        budget.admit()
        budget.finish()

    def test_f3_5_disk_budget_stops_accumulation(self):
        records = self.state_dir / "jobs"
        records.mkdir(parents=True)
        (records / "bulk.bin").write_bytes(b"x" * 4096)
        budget = WorkerBudget(self.state_dir, max_disk_bytes=1024, clock=lambda: self.clock[0])

        with self.assertRaises(BudgetExceeded) as caught:
            budget.admit()
        self.assertIn("disk", str(caught.exception))

    def test_worktree_count_limit_stops_accumulation(self):
        for name in ("a", "b"):
            (self.state_dir / "worktrees" / name).mkdir(parents=True)
        budget = WorkerBudget(self.state_dir, max_worktrees=2, clock=lambda: self.clock[0])

        with self.assertRaises(BudgetExceeded):
            budget.admit()

    def test_refused_jobs_create_no_worktree_and_no_claude_call(self):
        gateway = FakeGateway([_job()])
        worker, _ = self._worker(gateway, jobs_per_window=1)
        WorkerBudget(self.state_dir, jobs_per_window=1, clock=lambda: self.clock[0]).admit()

        worker.process_one_job()

        self.assertEqual(self.claude.implement_calls, 0)
        worktrees = self.bridge.worktrees_dir
        self.assertFalse(worktrees.exists() and any(worktrees.iterdir()))

    def test_budget_exhaustion_does_not_bypass_ownership_checks(self):
        gateway = FakeGateway([_job(developer_id="mallory")])
        worker, _ = self._worker(gateway, jobs_per_window=1)
        WorkerBudget(self.state_dir, jobs_per_window=1, clock=lambda: self.clock[0]).admit()

        worker.process_one_job()

        self.assertEqual(self.claude.implement_calls, 0)
        self.assertEqual(len(gateway.failures), 1)


class FailClosedTest(BudgetTestCase):
    def test_corrupt_state_file_refuses_jobs(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "worker_budget.json").write_text("{not json", encoding="utf-8")
        budget = WorkerBudget(self.state_dir, clock=lambda: self.clock[0])

        with self.assertRaises(BudgetExceeded) as caught:
            budget.admit()
        self.assertIn("unreadable", str(caught.exception))

    def test_wrong_shape_state_file_refuses_jobs(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "worker_budget.json").write_text(json.dumps({"starts": "many"}), encoding="utf-8")

        with self.assertRaises(BudgetExceeded):
            WorkerBudget(self.state_dir, clock=lambda: self.clock[0]).admit()

    def test_unmeasurable_disk_refuses_jobs(self):
        budget = WorkerBudget(self.state_dir, clock=lambda: self.clock[0])
        with mock.patch.object(budget_module, "_tree_bytes", side_effect=OSError("denied")):
            with self.assertRaises(BudgetExceeded):
                budget.admit()

    def test_limits_must_be_positive_integers(self):
        for bad in (0, -1, True, 1.5, "10", None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                WorkerBudget(self.state_dir, jobs_per_window=bad)

    def test_state_file_is_never_inside_a_job_payload_or_worktree(self):
        budget = WorkerBudget(self.state_dir, clock=lambda: self.clock[0])

        self.assertEqual(budget.state_path.parent, self.state_dir)
        self.assertNotIn(self.bridge.worktrees_dir, budget.state_path.parents)


if __name__ == "__main__":
    unittest.main()
