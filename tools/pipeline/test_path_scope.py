"""Path authorization for developers and bridge jobs: allow-lists, a global control-plane denylist, and fail-closed matching.

Run: python -m unittest tools.pipeline.test_path_scope -v
"""

import unittest

from .path_scope import allowed_path, is_control_plane, normalize_path

MANAGER_MODULES = (
    "README.md", "CONTRIBUTING.md", "docs/", "frontend/", "backend/", "database/", "tests/",
    "prototypes/", ".github/ISSUE_TEMPLATE/", ".github/pull_request_template.md",
)


class AllowedPathsTest(unittest.TestCase):
    def test_legitimate_project_paths_are_allowed(self):
        for path in ("README.md", "CONTRIBUTING.md", "docs/architecture/x.md", "frontend/app.tsx",
                     "backend/api/routes.py", "database/schema.sql", "tests/test_api.py", "prototypes/screen.html",
                     ".github/ISSUE_TEMPLATE/bug_report.md", ".github/pull_request_template.md"):
            with self.subTest(path=path):
                self.assertTrue(allowed_path(path, MANAGER_MODULES))

    def test_file_entries_match_exactly_not_by_prefix(self):
        self.assertFalse(allowed_path("README.md.bak", MANAGER_MODULES))
        self.assertFalse(allowed_path("README.mdx", MANAGER_MODULES))
        self.assertFalse(allowed_path("readme.md", MANAGER_MODULES))  # case-sensitive allow match

    def test_directory_entries_do_not_match_similar_names(self):
        self.assertFalse(allowed_path("frontendx/app.tsx", MANAGER_MODULES))
        self.assertFalse(allowed_path("docsold/a.md", MANAGER_MODULES))

    def test_paths_outside_the_allow_list_are_denied(self):
        for path in ("scripts/run.sh", "infra/main.tf", "LICENSE", ".env.example.bak"):
            with self.subTest(path=path):
                self.assertFalse(allowed_path(path, MANAGER_MODULES))

    def test_empty_or_missing_modules_fail_closed(self):
        self.assertFalse(allowed_path("docs/a.md", ()))
        self.assertFalse(allowed_path("docs/a.md", None))


class ControlPlaneTest(unittest.TestCase):
    def test_agent_bridge_code_and_deployment_are_control_plane(self):
        for path in ("tools/pipeline/bridge.py", "tools/pipeline/gateway/x.py", "tools/pipeline/deploy/README.md",
                     "tools/pipeline/deploy/windows/worker.env.example", "tools/pipeline/worker_daemon.py",
                     "tools/pipeline/deploy/windows/install-worker-task.ps1"):
            with self.subTest(path=path):
                self.assertTrue(is_control_plane(path))

    def test_ci_workflows_and_code_ownership_are_control_plane(self):
        self.assertTrue(is_control_plane(".github/workflows/ci.yml"))
        self.assertTrue(is_control_plane(".github/CODEOWNERS"))

    def test_sensitive_names_are_control_plane_anywhere(self):
        for path in ("frontend/.env", "backend/keys/service.key", "docs/cert.pem", "database/secrets/prod.txt"):
            with self.subTest(path=path):
                self.assertTrue(is_control_plane(path))

    def test_control_plane_wins_over_a_wildcard_allow(self):
        self.assertFalse(allowed_path("tools/pipeline/bridge.py", ("*",)))
        self.assertFalse(allowed_path(".github/workflows/ci.yml", ("*",)))

    def test_traversal_cannot_reach_control_plane(self):
        for path in ("frontend/../tools/pipeline/bridge.py", "docs/../.github/workflows/ci.yml", "../tools/pipeline/x.py"):
            with self.subTest(path=path):
                self.assertFalse(allowed_path(path, ("*", "frontend/", "docs/")))
                self.assertTrue(is_control_plane(path))

    def test_absolute_and_drive_paths_cannot_reach_control_plane(self):
        for path in ("/tools/pipeline/bridge.py", "C:/Users/x/tools/pipeline/bridge.py", "C:\\repo\\tools\\pipeline\\bridge.py"):
            with self.subTest(path=path):
                self.assertFalse(allowed_path(path, ("*",)))

    def test_backslashes_cannot_bypass_control_plane(self):
        self.assertTrue(is_control_plane("tools\\pipeline\\bridge.py"))
        self.assertFalse(allowed_path("tools\\pipeline\\bridge.py", ("*",)))

    def test_case_variants_cannot_bypass_control_plane(self):
        for path in ("TOOLS/Pipeline/bridge.py", "Tools/PIPELINE/deploy/README.md", ".GitHub/Workflows/ci.yml"):
            with self.subTest(path=path):
                self.assertTrue(is_control_plane(path))
                self.assertFalse(allowed_path(path, ("*",)))

    def test_similar_names_are_not_control_plane(self):
        self.assertFalse(is_control_plane("tools/pipeline_notes/readme.md"))
        self.assertFalse(is_control_plane("tools/pipelinex.py"))
        self.assertFalse(is_control_plane("docs/pipeline-overview.md"))

    def test_unparseable_paths_fail_closed(self):
        self.assertTrue(is_control_plane(""))
        self.assertTrue(is_control_plane("docs/./../../etc/passwd"))
        self.assertIsNone(normalize_path("../x"))


class NormalizationTest(unittest.TestCase):
    def test_leading_slash_and_backslash_are_normalized(self):
        self.assertEqual(normalize_path("\\docs\\a.md"), "docs/a.md")
        self.assertEqual(normalize_path("/docs/a.md"), "docs/a.md")


if __name__ == "__main__":
    unittest.main()
