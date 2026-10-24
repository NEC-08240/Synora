"""Lead session state: creation, restart persistence, idempotent jobs, fail-closed states.

Run: python -m unittest tools.pipeline.test_lead_state -v
"""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from .lead_state import (
    JOB_DONE,
    JOB_INTERRUPTED,
    JOB_PENDING,
    LeadState,
    LeadStateError,
    STATE_ACTIVE,
    STATE_BROKEN,
    STATE_CREATING,
    STATE_UNINITIALIZED,
)


class LeadStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "lead_state.json"
        self.session_id = str(uuid.uuid4())

    def tearDown(self):
        self._tmp.cleanup()

    def _active(self):
        state = LeadState.load(self.path)
        state.begin_create(self.session_id)
        state.mark_active(self.session_id)
        return state

    def test_new_store_is_uninitialized(self):
        state = LeadState.load(self.path)
        self.assertEqual(state.status, STATE_UNINITIALIZED)
        self.assertIsNone(state.session_id)

    def test_session_id_survives_a_new_process(self):
        self._active()
        reloaded = LeadState.load(self.path)
        self.assertEqual(reloaded.status, STATE_ACTIVE)
        self.assertEqual(reloaded.session_id, self.session_id)

    def test_create_is_persisted_before_the_claude_call(self):
        state = LeadState.load(self.path)
        state.begin_create(self.session_id)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["state"], STATE_CREATING)
        self.assertEqual(on_disk["session_id"], self.session_id)

    def test_interrupted_create_fails_closed_on_restart(self):
        LeadState.load(self.path).begin_create(self.session_id)
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).ensure_usable()

    def test_corrupt_file_fails_closed(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path)

    def test_unknown_schema_fails_closed(self):
        self.path.write_text(json.dumps({"schema": 99, "state": STATE_ACTIVE}), encoding="utf-8")
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path)

    def test_cannot_create_twice(self):
        self._active()
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).begin_create(str(uuid.uuid4()))

    def test_rejects_a_malformed_session_id(self):
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).begin_create("not-a-uuid")

    def test_environment_session_id_must_match_stored_one(self):
        self._active()
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).ensure_usable(expected_session_id=str(uuid.uuid4()))

    def test_repeated_job_returns_stored_outcome_and_is_not_rerun(self):
        state = self._active()
        state.begin_turn("job-1", "rajaneesh")
        state.finish_turn("job-1", {"status": "SUCCEEDED", "result": "done"}, cost_usd=0.01)
        again = LeadState.load(self.path)
        self.assertEqual(again.job_status("job-1"), JOB_DONE)
        self.assertEqual(again.stored_outcome("job-1"), {"status": "SUCCEEDED", "result": "done"})
        with self.assertRaises(LeadStateError):
            again.begin_turn("job-1", "rajaneesh")

    def test_pending_job_found_after_restart_is_interrupted_not_rerun(self):
        state = self._active()
        state.begin_turn("job-2", "rajaneesh")
        restarted = LeadState.load(self.path)
        self.assertEqual(restarted.job_status("job-2"), JOB_PENDING)
        restarted.mark_interrupted_jobs()
        self.assertEqual(LeadState.load(self.path).job_status("job-2"), JOB_INTERRUPTED)
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).begin_turn("job-2", "rajaneesh")

    def test_cost_and_turns_accumulate(self):
        state = self._active()
        state.begin_turn("job-a", "rajaneesh")
        state.finish_turn("job-a", {"status": "SUCCEEDED"}, cost_usd=0.02)
        state.begin_turn("job-b", "johan-admin")
        state.finish_turn("job-b", {"status": "SUCCEEDED"}, cost_usd=0.03)
        reloaded = LeadState.load(self.path)
        self.assertEqual(reloaded.turns, 2)
        self.assertAlmostEqual(reloaded.cumulative_cost_usd, 0.05)

    def test_broken_state_blocks_every_turn(self):
        self._active()
        state = LeadState.load(self.path)
        state.mark_broken("session mismatch", evidence={"expected": self.session_id, "returned": "other"})
        with self.assertRaises(LeadStateError):
            LeadState.load(self.path).ensure_usable()
        self.assertEqual(LeadState.load(self.path).status, STATE_BROKEN)

    def test_stored_outcome_is_bounded(self):
        state = self._active()
        state.begin_turn("job-big", "rajaneesh")
        state.finish_turn("job-big", {"status": "SUCCEEDED", "result": "x" * 100_000}, cost_usd=0.0)
        stored = LeadState.load(self.path).stored_outcome("job-big")
        self.assertLessEqual(len(stored["result"]), 8000)

    def test_stored_outcome_is_redacted(self):
        state = self._active()
        state.begin_turn("job-secret", "rajaneesh")
        state.finish_turn("job-secret", {"status": "SUCCEEDED", "result": "token sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456 used"}, cost_usd=0.0)
        stored = LeadState.load(self.path).stored_outcome("job-secret")
        self.assertNotIn("sk-ant-api03", stored["result"])


if __name__ == "__main__":
    unittest.main()
