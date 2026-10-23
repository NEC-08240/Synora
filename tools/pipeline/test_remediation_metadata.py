"""F6: metadata from the Gateway is validated before any security-sensitive use. Run: python -m unittest tools.pipeline.test_remediation_metadata -v"""

import tempfile
import unittest
import uuid
from pathlib import Path

from .authorization import AuthorizationError, AuthorizationPolicy
from .bridge import Bridge
from .metadata import MAX_METADATA_CHARS, validate_branch, validate_developer_id, validate_job_payload, validate_repository
from .team_registry import DEVELOPER_ID_PATTERN, DeveloperEntry

HOSTILE_TEXT = [
    "", " ", "../x", "../../etc/passwd", "/etc/passwd", "C:/Windows/System32", "C:\\Windows",
    "\\\\server\\share", "alice\n", "alice\r\n", "alice\x00", "ali\tce", "a" * 300,
    "alice; whoami", "alice$(id)", "alice`id`", "alice|id", "alice&&id", "alice\u200b",
    "ａｌｉｃｅ", "https://evil.example/x", "file:///etc/passwd", "git@github.com:x/y.git",
    "x/../../y", "feature/x..y/../z",
]


class DeveloperIdTest(unittest.TestCase):
    def test_valid_identifier_is_accepted(self):
        self.assertEqual(validate_developer_id("alice-01_b"), "alice-01_b")

    def test_hostile_identifiers_are_refused(self):
        for value in HOSTILE_TEXT:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_developer_id(value)

    def test_non_string_values_are_refused(self):
        for value in (None, 7, ["alice"], {"id": "alice"}, b"alice"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_developer_id(value)

    def test_registry_pattern_no_longer_accepts_trailing_newline(self):
        self.assertIsNone(DEVELOPER_ID_PATTERN.match("alice\n"))


class RepositoryTest(unittest.TestCase):
    def test_owner_and_name_is_accepted(self):
        self.assertEqual(validate_repository("NEC-08240/Synora"), "NEC-08240/Synora")

    def test_absent_repository_uses_the_default(self):
        self.assertEqual(validate_repository(None), "NEC-08240/Synora")
        self.assertEqual(validate_repository(""), "NEC-08240/Synora")

    def test_hostile_repositories_are_refused(self):
        for value in [v for v in HOSTILE_TEXT if v] + ["owner/name/extra", "owner", "owner/", "/name", "own er/name",
                                     "owner/na;me", "owner/..", "owner/name\n", "owner/name?x=1"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_repository(value)

    def test_oversized_repository_is_refused(self):
        with self.assertRaises(ValueError):
            validate_repository("a" * 40 + "/" + "b" * 200)


class BranchTest(unittest.TestCase):
    def test_strict_branch_rules_are_kept(self):
        self.assertEqual(validate_branch("feature/fe-a"), "feature/fe-a")

    def test_command_and_path_style_branches_are_refused(self):
        for value in ("feature/test; whoami", "feature/foo$(id)", "../outside", "/abs/path",
                      "feature/x\n", "feature/x\x00", "feature/x y", "feature/" + "a" * 260, "C:\\x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_branch(value)

    def test_absent_branch_is_none(self):
        self.assertIsNone(validate_branch(None))
        self.assertIsNone(validate_branch(""))

    def test_authorization_no_longer_accepts_a_trailing_newline_branch(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric import ed25519

        pub = base64.b64encode(ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()
        dev = DeveloperEntry(developer_id="alice", developer_name="A", github_username="a", role="developer",
                             status="active", public_key_ed25519=pub, assigned_modules=("*",), allowed_branches=("*",))
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(dev, "feature/fe-a\n", "docs")


class JobPayloadTest(unittest.TestCase):
    def test_oversized_payload_is_refused(self):
        with self.assertRaises(ValueError):
            validate_job_payload({"job_id": "j", "developer_id": "alice", "task": "x" * 200000, "task_type": "docs"})

    def test_missing_job_id_is_refused(self):
        with self.assertRaises(ValueError):
            validate_job_payload({"developer_id": "alice", "task": "x", "task_type": "docs"})


class BridgeBoundaryTest(unittest.TestCase):
    """Validation must also happen inside the bridge, so a caller that skips the Worker still cannot pass bad metadata."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bridge = Bridge(repo_root=Path(self._tmp.name), runner=lambda *a, **k: (0, "{}", ""))

    def tearDown(self):
        self._tmp.cleanup()

    def test_bridge_create_refuses_hostile_metadata_and_writes_no_record(self):
        cases = [
            {"developer_id": "../x"}, {"developer_id": "alice\n"},
            {"repository": "../../etc"}, {"branch": "feature/test; whoami"}, {"branch": "../outside"},
        ]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.bridge.create("write docs", "docs", **extra)
        self.assertFalse(self.bridge.records_dir.exists() and any(self.bridge.records_dir.iterdir()))

    def test_bridge_create_accepts_valid_metadata(self):
        record = self.bridge.create("write docs", "docs", developer_id="alice", repository="NEC-08240/Synora", branch="feature/fe-a")
        self.assertEqual(record["branch"], "feature/fe-a")


if __name__ == "__main__":
    unittest.main()
