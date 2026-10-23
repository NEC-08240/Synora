"""Regression tests for secret redaction in audit records and Worker results. Run: python -m unittest tools.pipeline.test_security_audit -v"""

import tempfile
import unittest
from pathlib import Path

from .audit import AuditLogger, redact_secret_values, scrub_sensitive
from .worker import sanitize_worker_result


class SecretValueRedactionTest(unittest.TestCase):
    def test_audit_redacts_secret_formats_inside_free_text(self):
        scrubbed = scrub_sensitive({"note": "key sk-ant-api03-" + "A" * 40})

        self.assertNotIn("sk-ant-api03-", scrubbed["note"])
        self.assertIn("[REDACTED_SECRET]", scrubbed["note"])

    def test_every_github_token_family_is_redacted(self):
        for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            with self.subTest(prefix=prefix):
                self.assertNotIn(prefix + "b" * 36, redact_secret_values(prefix + "b" * 36))

    def test_fine_grained_github_token_is_redacted(self):
        self.assertNotIn("github_pat_", redact_secret_values("github_pat_" + "c" * 60))

    def test_worker_result_uses_the_same_patterns(self):
        cleaned = sanitize_worker_result({"claude_result": "ghu_" + "e" * 36})

        self.assertNotIn("ghu_", cleaned["claude_result"])

    def test_audit_file_on_disk_contains_no_secret_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "audit.jsonl"
            AuditLogger(log).record("TEST", "dev", {"note": "ghs_" + "d" * 36})

            self.assertNotIn("ghs_" + "d" * 36, log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
