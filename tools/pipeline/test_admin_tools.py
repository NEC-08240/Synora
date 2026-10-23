"""Tests for the admin and teammate command-line tools. Run: python -m unittest tools.pipeline.test_admin_tools -v"""

import base64
import contextlib
import io
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import admin_cli, teammate_cli
from .team_registry import TeamRegistry
from .worker import load_worker_private_key
from .worker_registry import WorkerRegistry


def _run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class KeygenTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_key_file_is_raw_32_bytes_and_matches_the_published_public_key(self):
        path, public_b64 = admin_cli.keygen(self.dir, "alice")

        raw = path.read_bytes()
        self.assertEqual(len(raw), 32)
        derived = ed25519.Ed25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.assertEqual(base64.b64encode(derived).decode(), public_b64)
        self.assertEqual((self.dir / "alice.pub").read_text().strip(), public_b64)

    def test_the_worker_loader_accepts_the_generated_key(self):
        path, public_b64 = admin_cli.keygen(self.dir, "worker")
        loaded = load_worker_private_key(key_file=str(path))

        derived = loaded.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.assertEqual(base64.b64encode(derived).decode(), public_b64)

    def test_keygen_never_overwrites_an_existing_private_key(self):
        path, _ = admin_cli.keygen(self.dir, "alice")
        original = path.read_bytes()

        code, _out, err = _run(admin_cli.main, ["keygen", "--out-dir", str(self.dir), "--name", "alice"])

        self.assertEqual(code, 2)
        self.assertIn("error", err)
        self.assertEqual(path.read_bytes(), original)

    def test_nothing_in_the_output_reveals_the_private_key(self):
        code, out, _err = _run(admin_cli.main, ["keygen", "--out-dir", str(self.dir), "--name", "bob"])
        private_b64 = base64.b64encode((self.dir / "bob.key").read_bytes()).decode()

        self.assertEqual(code, 0)
        self.assertNotIn(private_b64, out)


class EnrolmentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _path, self.public_b64 = admin_cli.keygen(self.dir, "dev")

    def tearDown(self):
        self._tmp.cleanup()

    def _add_developer(self, developer_id="alice", **extra):
        argv = ["add-developer", "--registry", str(self.dir / "team.json"), "--developer-id", developer_id,
                "--name", "Alice", "--github", "alice-gh", "--public-key", self.public_b64]
        for key, value in extra.items():
            argv += [f"--{key}", value]
        return _run(admin_cli.main, argv)

    def test_developer_round_trips_through_the_registry_file(self):
        code, _out, _err = self._add_developer(modules="docs/,frontend/", branches="feature/*")

        entry = TeamRegistry.load(self.dir / "team.json").get("alice")
        self.assertEqual(code, 0)
        self.assertTrue(entry.can_touch_file("docs/agent-bridge/x.md"))
        self.assertTrue(entry.can_touch_file("frontend/app.js"))
        self.assertFalse(entry.can_touch_file("backend/server.js"))
        self.assertTrue(entry.can_touch_branch("feature/anything"))
        self.assertFalse(entry.can_touch_branch("main"))
        self.assertEqual(entry.status, "active")

    def test_glob_module_scopes_are_refused_because_they_would_match_nothing(self):
        code, _out, err = self._add_developer(modules="docs/*")

        self.assertEqual(code, 2)
        self.assertIn("directory prefixes", err)
        self.assertFalse((self.dir / "team.json").exists())

    def test_duplicate_developer_is_refused_and_the_file_is_unchanged(self):
        self._add_developer()
        before = (self.dir / "team.json").read_text()

        code, _out, err = self._add_developer()

        self.assertEqual(code, 2)
        self.assertIn("error", err)
        self.assertEqual((self.dir / "team.json").read_text(), before)

    def test_invalid_developer_ids_and_keys_are_refused(self):
        for bad_id in ("-x", "a", "alice\n", "../x", "a b"):
            with self.subTest(developer_id=bad_id):
                self.assertEqual(self._add_developer(developer_id=bad_id)[0], 2)
        code, _out, _err = _run(admin_cli.main, ["add-developer", "--registry", str(self.dir / "t2.json"), "--developer-id", "bob",
                                                 "--name", "Bob", "--github", "bob-gh", "--public-key", "not-a-key"])
        self.assertEqual(code, 2)

    def test_worker_round_trips_and_a_duplicate_is_refused(self):
        argv = ["add-worker", "--registry", str(self.dir / "workers.json"), "--worker-id", "worker-johan", "--public-key", self.public_b64]

        self.assertEqual(_run(admin_cli.main, argv)[0], 0)
        self.assertEqual(WorkerRegistry(str(self.dir / "workers.json")).get("worker-johan").status, "active")
        self.assertEqual(_run(admin_cli.main, argv)[0], 2)


class CertificateTest(unittest.TestCase):
    def test_generated_certificate_is_trustable_for_its_ip_and_reports_a_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key, fingerprint = admin_cli.gen_cert(tmp, "127.0.0.1", 30)

            self.assertEqual(len(fingerprint), 64)
            ssl.create_default_context(cafile=cert)  # raises if the file is not a usable trust anchor
            self.assertTrue(Path(key).exists())


class TeammateCliTest(unittest.TestCase):
    def test_missing_configuration_is_reported_by_name(self):
        code, _out, _err = _run(teammate_cli.main, ["status", "job-1"])
        self.assertNotEqual(code, 0)

    def test_a_key_file_that_is_not_32_bytes_is_refused_with_the_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.key"
            bad.write_text("not a raw key", encoding="utf-8")
            code, _out, err = _run(teammate_cli.main, ["--url", "https://gw.example", "--developer-id", "alice",
                                                      "--key-file", str(bad), "status", "job-1"])

        self.assertNotEqual(code, 0)


class WorkerKeyAndBaseCommitTest(unittest.TestCase):
    def test_worker_public_key_loads_from_a_pub_file_or_base64_and_rejects_anything_else(self):
        from .remote_shim import load_worker_public_key

        with tempfile.TemporaryDirectory() as tmp:
            _path, public_b64 = admin_cli.keygen(tmp, "w")
            from_file = load_worker_public_key(str(Path(tmp) / "w.pub"))
            from_text = load_worker_public_key(public_b64)
            self.assertEqual(from_file.public_bytes_raw(), from_text.public_bytes_raw())
        for bad in ("not base64!", "", base64.b64encode(b"short").decode()):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    load_worker_public_key(bad)

    def test_smoke_refuses_to_run_without_the_worker_public_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            key, _pub = admin_cli.keygen(tmp, "dev")
            env = {"SYNORA_GATEWAY_URL": "https://gw.example", "SYNORA_DEVELOPER_ID": "alice", "SYNORA_DEVELOPER_KEY_FILE": str(key)}
            with mock.patch.dict("os.environ", env, clear=True):
                code, _out, err = _run(teammate_cli.main, ["smoke"])

        self.assertNotEqual(code, 0)
        self.assertIn("SYNORA_WORKER_PUBLIC_KEY", str(code) + err)

    def test_the_default_base_commit_is_a_real_commit_of_the_callers_checkout(self):
        import subprocess

        from .remote_shim import default_base_commit

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "x"], cwd=tmp, check=True)
            expected = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(default_base_commit(tmp), expected)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                default_base_commit(tmp)


if __name__ == "__main__":
    unittest.main()
