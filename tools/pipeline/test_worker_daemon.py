"""Tests for the Worker daemon's env file and logging. Run: python -m unittest tools.pipeline.test_worker_daemon -v"""

import logging
import tempfile
import unittest
from pathlib import Path

from . import worker_daemon


class EnvFileTest(unittest.TestCase):
    def _load(self, text, environ=None):
        environ = {} if environ is None else environ
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worker.env"
            path.write_text(text, encoding="utf-8")
            worker_daemon.load_env_file(path, environ)
        return environ

    def test_synora_settings_are_loaded_and_comments_and_blank_lines_are_skipped(self):
        loaded = self._load("# comment\n\nSYNORA_WORKER_ID = worker-x\nSYNORA_GATEWAY_URL=wss://gw.example\n")

        self.assertEqual(loaded, {"SYNORA_WORKER_ID": "worker-x", "SYNORA_GATEWAY_URL": "wss://gw.example"})

    def test_names_outside_the_synora_namespace_are_ignored(self):
        loaded = self._load("PATH=C:\\evil\nPYTHONPATH=C:\\evil\nSYNORA_WORKER_ID=worker-x\nnot a setting\nsynora_lower=x\n")

        self.assertEqual(loaded, {"SYNORA_WORKER_ID": "worker-x"})

    def test_a_value_already_in_the_environment_wins(self):
        loaded = self._load("SYNORA_GATEWAY_URL=wss://from-file\n", {"SYNORA_GATEWAY_URL": "wss://from-env"})

        self.assertEqual(loaded["SYNORA_GATEWAY_URL"], "wss://from-env")

    def test_a_missing_file_is_an_error_not_silence(self):
        with self.assertRaises(OSError):
            worker_daemon.load_env_file("does-not-exist.env", {})


class LoggingTest(unittest.TestCase):
    def tearDown(self):
        logging.basicConfig(force=True)  # drop the file handler so the temp folder can be removed

    def test_logs_go_to_the_configured_file_with_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "logs" / "worker.log"
            worker_daemon.configure_logging({"SYNORA_WORKER_LOG_FILE": str(log)})
            logging.getLogger("synora.worker").info("hello from the test")
            for handler in logging.getLogger().handlers:
                handler.flush()
            text = log.read_text(encoding="utf-8")
            logging.basicConfig(force=True)

        self.assertIn("hello from the test", text)
        self.assertRegex(text, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO synora.worker: ")

    def test_a_configuration_error_exits_non_zero_and_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "worker.env"
            env_file.write_text("SYNORA_LOG_ONLY=1\n", encoding="utf-8")
            log = Path(tmp) / "worker.log"
            import os
            from unittest import mock

            with mock.patch.dict(os.environ, {"SYNORA_WORKER_LOG_FILE": str(log)}, clear=True):
                with self.assertRaises(SystemExit) as raised:
                    worker_daemon.main(["--env-file", str(env_file)])
                for handler in logging.getLogger().handlers:
                    handler.flush()
                text = log.read_text(encoding="utf-8")
            logging.basicConfig(force=True)

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Configuration error", text)


if __name__ == "__main__":
    unittest.main()
