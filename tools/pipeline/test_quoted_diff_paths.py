import unittest

from .contribution_gate import ContributionGateError, extract_files_from_diff


class TestQuotedDiffPathsFailClosed(unittest.TestCase):
    """git quotes paths with non-ASCII or special characters; the gate must not skip them."""

    def test_quoted_header_is_rejected_not_skipped(self):
        # Arrange: an out-of-scope file whose name git would quote (non-ASCII).
        quoted_diff = (
            'diff --git "a/backend/s\\303\\251rv.py" "b/backend/s\\303\\251rv.py"\n'
            '--- "a/backend/s\\303\\251rv.py"\n'
            '+++ "b/backend/s\\303\\251rv.py"\n'
            '@@ -1 +1 @@\n-x\n+y\n'
        )

        # Act / Assert
        with self.assertRaises(ContributionGateError) as ctx:
            extract_files_from_diff(quoted_diff)
        self.assertIn('quoted', str(ctx.exception).lower())

    def test_quoted_minus_header_alone_is_rejected(self):
        # Arrange: unquoted diff header but a quoted ---/+++ line.
        mixed_diff = (
            'diff --git a/frontend/ok.js b/frontend/ok.js\n'
            '--- "a/backend/x y.py"\n'
            '+++ b/frontend/ok.js\n'
            '@@ -1 +1 @@\n-a\n+b\n'
        )

        # Act / Assert
        with self.assertRaises(ContributionGateError):
            extract_files_from_diff(mixed_diff)

    def test_plain_diff_still_extracts_files(self):
        # Arrange
        plain_diff = (
            'diff --git a/frontend/ok.js b/frontend/ok.js\n'
            '--- a/frontend/ok.js\n'
            '+++ b/frontend/ok.js\n'
            '@@ -1 +1 @@\n-a\n+b\n'
        )

        # Act
        files = extract_files_from_diff(plain_diff)

        # Assert
        self.assertEqual(files, ['frontend/ok.js'])
