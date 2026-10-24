"""Independent implementation jobs run concurrently while the Lead's turns stay serialized.

Three Worker instances, each with its own identity, claim jobs from one real queue. Three developers submit
implementation jobs and two developers submit Lead jobs. The test proves:
  - implementation jobs overlap in time (no global Worker lock);
  - Lead turns never overlap each other (the Lead mutex);
  - at least one Lead turn overlaps implementation work (the Lead does not block the workforce);
  - every job is claimed once and completes.
Fakes stand in for Claude, so no API budget is spent. Run: python -m unittest tools.pipeline.test_lead_concurrency -v
"""

import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from .lead import LeadRunner
from .queue import JobQueue
from .worker import OutboundWorker

BRIDGE_SECONDS = 1.2  # long enough that Lead turns run while implementation work is still in progress
LEAD_SECONDS = 0.25


class ConcurrentBridge:
    """Stands in for the bridge. Records when each implementation job runs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.intervals = []
        self.created = []

    def create(self, **kwargs):
        local_id = str(uuid.uuid4())
        with self.lock:
            self.created.append(local_id)
        return {"job_id": local_id, "_task": kwargs}

    def execute(self, job_id):
        start = time.monotonic()
        time.sleep(BRIDGE_SECONDS)
        with self.lock:
            self.intervals.append((start, time.monotonic(), job_id))

    def get(self, job_id):
        return {"status": "SUCCEEDED", "changed_files": ["docs/agent-bridge/x.md"], "base_commit": None}

    def resolve_base(self, requested):
        return requested


class FakeLeadClaude:
    """Behaves like the Lead's Claude: counts overlapping Lead calls and remembers them per session."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.intervals = []
        self.memory = {}

    def __call__(self, prompt, cwd, args):
        is_lead = "--session-id" in args or "--resume" in args
        start = time.monotonic()
        if is_lead:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
        try:
            if "REVIEW" in prompt:
                result = json.dumps({"verdict": "PASS", "evidence_limits": "fake", "findings": []})
                session_id = None
            else:
                time.sleep(LEAD_SECONDS)
                session_id = args[args.index("--resume") + 1] if "--resume" in args else args[args.index("--session-id") + 1]
                with self.lock:
                    self.memory.setdefault(session_id, []).append(prompt)
                result = f"decision recorded ({len(self.memory[session_id])})"
        finally:
            if is_lead:
                with self.lock:
                    self.active -= 1
                    self.intervals.append((start, time.monotonic(), session_id))
        return 0, json.dumps({
            "type": "result", "subtype": "success", "is_error": False, "result": result,
            "session_id": session_id or "review", "total_cost_usd": 0.01, "num_turns": 1,
        }), ""


class OpenBudget:
    def admit(self):
        pass

    def finish(self):
        pass


def _scope(modules=("docs/",), branches=("feature/*",)):
    return {"modules": list(modules), "branches": list(branches)}


class ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.queue = JobQueue(str(root / "gateway.db"))
        self.claude = FakeLeadClaude()
        self.lead = LeadRunner(
            state_path=root / "lead" / "state.json",
            mutex_path=root / "lead" / "lead.lock",
            workspace=root / "lead-ws",
            log_path=root / "lead" / "turns.jsonl",
            claude=self.claude,
        )
        self.bridge = ConcurrentBridge()
        self.claimed = []
        self.results = {}
        self.claim_lock = threading.Lock()

    def tearDown(self):
        self.queue.close()
        self._tmp.cleanup()

    def _enqueue(self):
        # Lead requests are queued first, so two workers take them while the third is already on implementation work.
        for dev in ("dev-a", "dev-b"):
            self.queue.enqueue({
                "job_id": str(uuid.uuid4()), "developer_id": dev, "task": f"Lead request from {dev}.",
                "task_type": "lead", "branch": f"feature/{dev}/work", "base_commit": "abc1234",
                "scope": _scope(branches=(f"feature/{dev}/*",)),
            })
        for dev in ("dev-a", "dev-b", "dev-c"):
            self.queue.enqueue({
                "job_id": str(uuid.uuid4()), "developer_id": dev, "task": f"Implementation for {dev}.",
                "task_type": "docs", "branch": f"feature/{dev}/work", "base_commit": "abc1234",
                "scope": _scope(branches=(f"feature/{dev}/*",)),
            })

    def _worker_loop(self, worker):
        while True:
            with self.claim_lock:
                job = self.queue.claim_next(worker.worker_id)
                if job is not None:
                    self.claimed.append(job["job_id"])
            if job is None:
                return
            try:
                result = worker.run_job_payload(job)
            except Exception as err:  # recorded, so the assertions show what went wrong
                result = {"status": "FAILED", "error": f"{type(err).__name__}: {err}"}
            with self.claim_lock:
                self.results[job["job_id"]] = result
            self.queue.complete_job(job["job_id"], worker.worker_id, result)

    def test_implementation_jobs_overlap_and_lead_turns_do_not(self):
        self._enqueue()
        workers = [
            OutboundWorker(worker_id=f"worker-{n}", bridge=self.bridge, budget=OpenBudget(), lead=self.lead)
            for n in ("a", "b", "c")
        ]
        threads = [threading.Thread(target=self._worker_loop, args=(w,)) for w in workers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        # Every job is claimed exactly once and completes.
        self.assertEqual(len(self.claimed), 5)
        self.assertEqual(len(set(self.claimed)), 5)
        self.assertEqual(len(self.results), 5)
        self.assertTrue(all(r["status"] == "SUCCEEDED" for r in self.results.values()))

        # Implementation jobs ran at the same time: at least two of the three intervals overlap.
        impl = sorted(self.bridge.intervals)
        self.assertEqual(len(impl), 3)
        self.assertTrue(any(impl[i][0] < impl[i + 1][1] for i in range(len(impl) - 1)),
                        f"implementation jobs were serialized: {impl}")
        self.assertGreaterEqual(_max_overlap(impl), 2)

        # Lead turns never overlapped each other.
        self.assertEqual(self.claude.max_active, 1)

        # A Lead turn ran while implementation work was in progress.
        lead = self.claude.intervals
        self.assertEqual(len(lead), 3)  # one session creation plus the two Lead turns
        self.assertTrue(any(_overlaps(l, i) for l in lead for i in impl),
                        "no Lead turn overlapped implementation work; the Lead may be blocking the workforce")

    def test_each_implementation_job_gets_its_own_local_job(self):
        self._enqueue()
        workers = [OutboundWorker(worker_id=f"worker-{n}", bridge=self.bridge, budget=OpenBudget(), lead=self.lead)
                   for n in ("a", "b", "c")]
        threads = [threading.Thread(target=self._worker_loop, args=(w,)) for w in workers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(len(set(self.bridge.created)), len(self.bridge.created))


def _overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def _max_overlap(intervals):
    events = sorted([(s, 1) for s, _, _ in intervals] + [(e, -1) for _, e, _ in intervals])
    best = current = 0
    for _, delta in events:
        current += delta
        best = max(best, current)
    return best


if __name__ == "__main__":
    unittest.main()
