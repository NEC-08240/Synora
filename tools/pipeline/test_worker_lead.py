"""The Worker routes `lead` jobs to the Lead and leaves every other job on the bridge.

Run: python -m unittest tools.pipeline.test_worker_lead -v
"""

import tempfile
import unittest
from pathlib import Path

from .lead import LeadScopeError
from .worker import LeadNotConfigured, OutboundWorker
from .worker_daemon import create_lead_runner


class RecordingBridge:
    def __init__(self):
        self.created = []
        self.executed = []
        self.records_dir = Path(tempfile.gettempdir()) / "unused-records"

    def create(self, **kwargs):
        self.created.append(kwargs)
        return {"job_id": "local-1"}

    def execute(self, job_id):
        self.executed.append(job_id)

    def get(self, job_id):
        return {"status": "SUCCEEDED", "changed_files": ["docs/agent-bridge/x.md"], "base_commit": None}

    def resolve_base(self, requested):
        return requested


class RecordingLead:
    def __init__(self, fail=False):
        self.turns = []
        self.fail = fail

    def run_turn(self, job):
        self.turns.append(job)
        if self.fail:
            raise LeadScopeError("The job carries no authorized scope; the Lead refuses it.")
        return {"status": "SUCCEEDED", "result": "decision", "review": {"verdict": "PASS"}, "cost_usd": 0.02}


class OpenBudget:
    def __init__(self):
        self.admitted = 0

    def admit(self):
        self.admitted += 1

    def finish(self):
        pass


LEAD_JOB = {
    "job_id": "11111111-1111-4111-8111-111111111111",
    "developer_id": "rajaneesh",
    "task": "Note the connectivity check in the docs.",
    "task_type": "lead",
    "branch": "feature/rajaneesh/notes",
    "base_commit": None,
    "scope": {"modules": ["docs/"], "branches": ["feature/rajaneesh/*"]},
}
DOCS_JOB = {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "developer_id": "rajaneesh",
    "task": "Add a one-line note to the docs.",
    "task_type": "docs",
    "branch": "feature/rajaneesh/notes",
    "base_commit": None,
}


class WorkerLeadRoutingTest(unittest.TestCase):
    def worker(self, lead=None):
        self.bridge = RecordingBridge()
        self.budget = OpenBudget()
        return OutboundWorker(worker_id="worker-test", bridge=self.bridge, budget=self.budget, lead=lead)

    def test_lead_job_goes_to_the_lead_and_never_to_the_bridge(self):
        lead = RecordingLead()
        worker = self.worker(lead)
        result = worker.run_job_payload(LEAD_JOB)
        self.assertEqual(len(lead.turns), 1)
        self.assertEqual(self.bridge.created, [])
        self.assertEqual(result["status"], "SUCCEEDED")

    def test_docs_job_still_goes_to_the_bridge(self):
        lead = RecordingLead()
        worker = self.worker(lead)
        worker.run_job_payload(DOCS_JOB)
        self.assertEqual(lead.turns, [])
        self.assertEqual(len(self.bridge.created), 1)

    def test_lead_job_is_refused_when_no_lead_is_configured(self):
        worker = self.worker(lead=None)
        with self.assertRaises(LeadNotConfigured):
            worker.run_job_payload(LEAD_JOB)
        self.assertEqual(self.bridge.created, [])

    def test_lead_job_counts_against_the_worker_budget(self):
        worker = self.worker(RecordingLead())
        worker._intake(LEAD_JOB)
        self.assertEqual(self.budget.admitted, 1)

    def test_lead_refusal_propagates_so_the_job_fails_closed(self):
        worker = self.worker(RecordingLead(fail=True))
        with self.assertRaises(LeadScopeError):
            worker.run_job_payload(LEAD_JOB)


class LeadConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.home.mkdir()
        self.repo.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_workspace_means_the_lead_is_disabled(self):
        self.assertIsNone(create_lead_runner({"lead_workspace": None, "lead_state_dir": None, "lead_session_id": None,
                                              "repo_root": str(self.repo), "home": str(self.home), "claude_bin": None}))

    def test_workspace_inside_the_secret_folder_stops_startup(self):
        with self.assertRaises(Exception):
            create_lead_runner({"lead_workspace": str(self.home / ".synora" / "lead"), "lead_state_dir": str(self.root / "state"),
                                "lead_session_id": None, "repo_root": str(self.repo), "home": str(self.home), "claude_bin": "claude"})

    def test_valid_workspace_builds_a_runner_with_state_under_the_state_folder(self):
        runner = create_lead_runner({"lead_workspace": str(self.root / "lead-ws"), "lead_state_dir": str(self.root / "state"),
                                     "lead_session_id": None, "repo_root": str(self.repo), "home": str(self.home),
                                     "claude_bin": "claude"})
        self.assertIsNotNone(runner)
        self.assertEqual(runner.state_path, self.root / "state" / "lead_state.json")
        self.assertTrue((self.root / "lead-ws").is_dir())


if __name__ == "__main__":
    unittest.main()
