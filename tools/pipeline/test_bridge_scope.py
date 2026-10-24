"""The bridge enforces the requester's module scope and the control plane on every changed file.

Run: python -m unittest tools.pipeline.test_bridge_scope -v
"""

import unittest

from .bridge import scope_violations


class ScopeViolationsTest(unittest.TestCase):
    def test_a_change_inside_the_requesters_modules_passes(self):
        self.assertEqual(scope_violations(["docs/agent-bridge/notes.md"], "docs", ["docs/"]), [])

    def test_a_change_the_task_type_allows_but_the_requester_may_not_make_is_refused(self):
        # `code` may write backend/, but this requester is scoped to frontend/ and tests/.
        violations = scope_violations(["backend/api.py"], "code", ["frontend/", "tests/"])
        self.assertEqual(violations, ["backend/api.py"])

    def test_control_plane_is_refused_even_for_a_wildcard_requester(self):
        self.assertEqual(scope_violations(["tools/pipeline/bridge.py"], "code", ["*"]), ["tools/pipeline/bridge.py"])
        self.assertEqual(scope_violations([".github/workflows/ci.yml"], "code", ["*"]), [".github/workflows/ci.yml"])

    def test_pipeline_files_are_refused_for_every_task_type(self):
        for task_type in ("docs", "code", "review"):
            with self.subTest(task_type=task_type):
                self.assertTrue(scope_violations(["tools/pipeline/worker.py"], task_type, ["*"]))

    def test_files_outside_the_task_type_scope_are_refused_without_a_module_scope(self):
        self.assertEqual(scope_violations(["README.md"], "docs", None), ["README.md"])

    def test_no_module_scope_still_allows_the_task_type_scope(self):
        self.assertEqual(scope_violations(["frontend/app.tsx"], "code", None), [])

    def test_traversal_in_a_changed_file_is_refused(self):
        violations = scope_violations(["docs/agent-bridge/../../tools/pipeline/bridge.py"], "docs", ["*"])
        self.assertTrue(violations)

    def test_violations_are_listed_once_and_sorted(self):
        violations = scope_violations(["frontend/b.ts", "backend/a.py", "backend/a.py"], "code", ["frontend/"])
        self.assertEqual(violations, ["backend/a.py"])


if __name__ == "__main__":
    unittest.main()
