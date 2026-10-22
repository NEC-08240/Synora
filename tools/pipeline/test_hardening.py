"""Tests for crash recovery, cleanup limits, and reviewer evidence. Run: python -m unittest tools.pipeline.test_hardening -v"""

import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from . import bridge as bridge_module
from .bridge import REVIEW_TOOLS, Bridge, _parse_verdict
from .records import DirectoryOwner
from .test_bridge import PASS_VERDICT, FakeClaude


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git_plain("init", "-q")
        (self.repo / "README.md").write_text("repo\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        self._git_plain("add", "README.md", ".gitignore")
        self._git_plain("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def _recover(self, bridge):
        owner = DirectoryOwner(bridge.records_dir).acquire()
        try:
            return bridge.recover_abandoned(owner)
        finally:
            owner.release()

    def _git_plain(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def _bridge(self, claude=None, verify=None):
        return Bridge(repo_root=self.repo, runner=claude or FakeClaude(), verify_commands=verify or {})

    def _abandon(self, bridge, status, with_worktree=True):
        """Create a job record stuck in `status`, optionally with its worktree still on disk."""
        job_id = bridge.create("Write it.", "docs")["job_id"]
        bridge._transition(job_id, "RUNNING")
        if status in ("VERIFYING", "REVIEWING"):
            bridge._transition(job_id, "VERIFYING")
        if status == "REVIEWING":
            bridge._transition(job_id, "REVIEWING")
        if with_worktree:
            worktree = bridge.worktrees_dir / job_id
            bridge.worktrees_dir.mkdir(parents=True, exist_ok=True)
            bridge._git(["worktree", "add", "--detach", str(worktree), "HEAD"], self.repo)
            _write(worktree, "docs/agent-bridge/partial.md", "half written\n")
        return job_id


def _write(root, relative_path, text):
    target = Path(root) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class RecoveryTest(RepoCase):
    def test_recovery_refuses_without_holding_the_lock(self):
        bridge = self._bridge()
        with self.assertRaises(RuntimeError):
            bridge.recover_abandoned(DirectoryOwner(bridge.records_dir))

    def test_abandoned_job_is_failed_with_the_reason_recorded(self):
        bridge = self._bridge()
        job_id = self._abandon(bridge, "RUNNING", with_worktree=False)

        report = self._recover(bridge)

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("was RUNNING", record["error"])
        self.assertEqual(report["failed_jobs"], [job_id])

    def test_abandoned_worktree_is_removed_and_the_repo_stays_clean(self):
        bridge = self._bridge()
        job_id = self._abandon(bridge, "RUNNING")

        report = self._recover(bridge)

        self.assertFalse((bridge.worktrees_dir / job_id).exists())
        self.assertEqual(report["removed_worktrees"], [job_id])
        self.assertNotIn(str(bridge.worktrees_dir / job_id), bridge._git(["worktree", "list"], self.repo))

    def test_crash_mid_verification_keeps_the_diagnosis(self):
        bridge = self._bridge()
        job_id = self._abandon(bridge, "VERIFYING")

        self._recover(bridge)

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("was VERIFYING", record["error"])
        self.assertEqual(record["task"], "Write it.")
        self.assertEqual(record["working_dir"], ".")

    def test_already_cleaned_worktree_is_not_an_error(self):
        bridge = self._bridge()
        job_id = self._abandon(bridge, "RUNNING", with_worktree=False)

        report = self._recover(bridge)

        self.assertEqual(bridge.get(job_id)["status"], "FAILED")
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["removed_worktrees"], [])

    def test_cleanup_failure_is_reported_and_recorded(self):
        bridge = self._bridge()
        job_id = self._abandon(bridge, "RUNNING")
        real_git = Bridge._git

        def blocked_remove(this, args, cwd):
            if args[:2] == ["worktree", "remove"]:
                raise RuntimeError("remove blocked")
            return real_git(this, args, cwd)

        with mock.patch.object(Bridge, "_git", new=blocked_remove):
            report = self._recover(bridge)

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("remove blocked", record["cleanup_error"])
        self.assertTrue(any("not removed" in problem for problem in report["problems"]))

    def test_malformed_record_does_not_stop_recovery_and_is_kept(self):
        bridge = self._bridge()
        good = self._abandon(bridge, "RUNNING", with_worktree=False)
        bad_id = str(uuid.uuid4())
        bridge.records_dir.mkdir(parents=True, exist_ok=True)
        bad_path = bridge.records_dir / f"{bad_id}.json"
        bad_path.write_text("{garbage", encoding="utf-8")

        report = self._recover(bridge)

        self.assertEqual(bridge.get(good)["status"], "FAILED")
        self.assertEqual(report["failed_jobs"], [good])
        self.assertTrue(any("not valid JSON" in problem for problem in report["problems"]))
        self.assertTrue(bad_path.exists())

    def test_unknown_folder_in_worktrees_is_left_alone(self):
        bridge = self._bridge()
        stray = bridge.worktrees_dir / "my-notes"
        _write(stray, "keep.txt", "important\n")

        report = self._recover(bridge)

        self.assertTrue((stray / "keep.txt").exists())
        self.assertTrue(any("my-notes" in problem for problem in report["problems"]))

    def test_uuid_named_folder_without_a_git_marker_is_left_alone(self):
        bridge = self._bridge()
        folder = bridge.worktrees_dir / str(uuid.uuid4())
        _write(folder, "precious.txt", "not a bridge worktree\n")

        report = self._recover(bridge)

        self.assertTrue((folder / "precious.txt").exists())
        self.assertTrue(any("not removed" in problem for problem in report["problems"]))

    def test_removal_refuses_paths_outside_the_worktree_folder(self):
        bridge = self._bridge()
        outside = self.root / "elsewhere"
        _write(outside, "data.txt", "keep\n")

        with self.assertRaises(RuntimeError):
            bridge._remove_worktree(outside)
        self.assertTrue((outside / "data.txt").exists())

    def test_symlinked_worktree_entry_is_refused(self):
        bridge = self._bridge()
        target = self.root / "real-folder"
        _write(target, "data.txt", "keep\n")
        bridge.worktrees_dir.mkdir(parents=True, exist_ok=True)
        link = bridge.worktrees_dir / str(uuid.uuid4())
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks need extra privileges on this machine")

        with self.assertRaises(RuntimeError):
            bridge._remove_worktree(link)
        self.assertTrue((target / "data.txt").exists())

    def test_partial_temp_files_are_removed_on_recovery(self):
        bridge = self._bridge()
        bridge.records_dir.mkdir(parents=True, exist_ok=True)
        partial = bridge.records_dir / f"{uuid.uuid4()}.json.x1.tmp"
        partial.write_text("{half", encoding="utf-8")

        self._recover(bridge)

        self.assertFalse(partial.exists())

    def test_recovery_is_idempotent(self):
        bridge = self._bridge()
        self._abandon(bridge, "RUNNING")
        self._recover(bridge)

        second = self._recover(bridge)

        self.assertEqual(second["failed_jobs"], [])
        self.assertEqual(second["removed_worktrees"], [])


class ReviewerEvidenceTest(RepoCase):
    def test_docs_review_carries_structured_evidence(self):
        bridge = self._bridge(FakeClaude(write="docs/agent-bridge/x.md"))
        job_id = bridge.create("Write it.", "docs")["job_id"]
        bridge.execute(job_id)

        evidence = bridge.get(job_id)["review"]["evidence"]

        self.assertTrue(evidence["documentation_only"])
        self.assertEqual(evidence["files"], ["docs/agent-bridge/x.md"])
        self.assertGreater(evidence["lines_added"], 0)
        self.assertEqual(evidence["verification_status"], "SCOPE_ONLY")
        self.assertIn("No test or build command was run", evidence["verification_note"])

    def test_reviewer_prompt_treats_the_claim_as_unverified_and_lists_the_evidence(self):
        claude = FakeClaude(write="docs/agent-bridge/x.md", text="All tests pass.")
        bridge = self._bridge(claude)
        job_id = bridge.create("Write it.", "docs")["job_id"]
        bridge.execute(job_id)

        review_prompt = claude.calls[1]["prompt"]

        self.assertIn("UNVERIFIED", review_prompt)
        self.assertIn("All tests pass.", review_prompt)
        self.assertIn('"documentation_only": true', review_prompt)
        self.assertIn("UNSUPPORTED_CLAIM", review_prompt)

    def test_reviewer_tools_are_read_only(self):
        self.assertEqual(set(REVIEW_TOOLS.split(",")), {"Read", "Glob", "Grep"})

    def test_unknown_finding_categories_are_coerced_to_other(self):
        verdict = json.dumps({
            "verdict": "CHANGES_REQUIRED",
            "evidence_limits": "No tests run.",
            "findings": [
                {"severity": "WARNING", "category": "SCOPE_VIOLATION", "file": "a", "detail": "x"},
                {"severity": "WARNING", "category": "MADE_UP", "file": "b", "detail": "y"},
            ],
        })
        parsed = _parse_verdict(verdict)

        self.assertEqual([f["category"] for f in parsed["findings"]], ["SCOPE_VIOLATION", "OTHER"])
        self.assertEqual(parsed["evidence_limits"], "No tests run.")

    def test_missing_evidence_limits_default_to_an_explicit_statement(self):
        parsed = _parse_verdict(PASS_VERDICT)

        self.assertEqual(parsed["evidence_limits"], "Not stated by the reviewer.")

    def test_evidence_limits_are_capped(self):
        verdict = json.dumps({"verdict": "PASS", "evidence_limits": "x" * 5000, "findings": []})
        parsed = _parse_verdict(verdict)

        self.assertLessEqual(len(parsed["evidence_limits"]), bridge_module.MAX_EVIDENCE_LIMITS_CHARS)


class CheckoutGuardTest(RepoCase):
    def test_bridge_state_does_not_count_as_a_checkout_change(self):
        """A repo that does not ignore .agents/pipeline must still run jobs: the bridge's own writes are excluded."""
        (self.repo / ".gitignore").unlink()
        self._git_plain("rm", "-q", "--cached", ".gitignore")
        self._git_plain("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "drop ignore")
        bridge = self._bridge(FakeClaude(write="docs/agent-bridge/x.md"))
        job_id = bridge.create("Write it.", "docs")["job_id"]

        bridge.execute(job_id)

        self.assertEqual(bridge.get(job_id)["status"], "SUCCEEDED", bridge.get(job_id)["error"])

    def test_a_change_to_the_checkout_during_a_job_fails_it(self):
        repo = self.repo

        def stray_writer(prompt, cwd, tools, permission_mode):
            _write(repo, "stray.txt", "outside the worktree\n")
            return FakeClaude(write="docs/agent-bridge/x.md")(prompt, cwd, tools, permission_mode)

        bridge = self._bridge(stray_writer)
        job_id = bridge.create("Write it.", "docs")["job_id"]
        bridge.execute(job_id)

        record = bridge.get(job_id)
        self.assertEqual(record["status"], "FAILED")
        self.assertIn("checkout changed", record["error"])


if __name__ == "__main__":
    unittest.main()
