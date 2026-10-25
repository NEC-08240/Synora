"""The intended Engineering Manager policy for rajaneesh, and unchanged behaviour for existing developers.

Run: python -m unittest tools.pipeline.test_manager_policy -v
"""

import unittest

from .authorization import AuthorizationError, AuthorizationPolicy
from .team_registry import DeveloperEntry

MANAGER_MODULES = (
    "README.md", "CONTRIBUTING.md", "docs/", "frontend/", "backend/", "database/", "tests/",
    "prototypes/", ".github/ISSUE_TEMPLATE/", ".github/pull_request_template.md",
)
MANAGER_BRANCHES = ("feature/rajaneesh/*", "fix/rajaneesh/*", "docs/rajaneesh/*", "prototype/rajaneesh/*")
KEY = "wnunJ+vRcdXakp0dTO6xapR/I7/QnVTf2bb/T7scOMg="


def _manager():
    return DeveloperEntry(
        developer_id="rajaneesh", developer_name="Rajaneesh T V", github_username="rajaneeshappu07-netizen",
        role="developer", status="active", public_key_ed25519=KEY,
        assigned_modules=MANAGER_MODULES, allowed_branches=MANAGER_BRANCHES,
    )


def _developer_docs_only():
    return DeveloperEntry(
        developer_id="docs-dev", developer_name="Docs", github_username="docs-gh", role="developer",
        status="active", public_key_ed25519=KEY, assigned_modules=("docs/",), allowed_branches=("feature/*",),
    )


class ManagerPolicyTest(unittest.TestCase):
    def setUp(self):
        self.manager = _manager()

    def test_manager_can_work_on_the_normal_project_areas(self):
        for path in ("README.md", "CONTRIBUTING.md", "docs/architecture/x.md", "frontend/app.tsx",
                     "backend/api.py", "database/schema.sql", "tests/test_api.py", "prototypes/screen.html",
                     ".github/ISSUE_TEMPLATE/bug_report.md", ".github/pull_request_template.md"):
            with self.subTest(path=path):
                self.assertTrue(self.manager.can_touch_file(path))

    def test_manager_cannot_touch_the_agent_bridge_or_its_secrets(self):
        for path in ("tools/pipeline/bridge.py", "tools/pipeline/gateway/gateway.py",
                     "tools/pipeline/worker/worker.py", "tools/pipeline/deploy/README.md",
                     "tools/pipeline/deploy/windows/worker.env.example", ".github/workflows/ci.yml",
                     ".github/CODEOWNERS", "backend/.env", "backend/keys/worker.key", "database/secrets/prod.txt"):
            with self.subTest(path=path):
                self.assertFalse(self.manager.can_touch_file(path))

    def test_manager_cannot_reach_the_pipeline_through_traversal_or_absolute_paths(self):
        for path in ("frontend/../tools/pipeline/bridge.py", "/tools/pipeline/bridge.py",
                     "C:/repo/tools/pipeline/bridge.py", "TOOLS/Pipeline/bridge.py"):
            with self.subTest(path=path):
                self.assertFalse(self.manager.can_touch_file(path))

    def test_manager_branches_are_his_namespaces_only(self):
        for branch in ("feature/rajaneesh/notes", "fix/rajaneesh/x", "docs/rajaneesh/y", "prototype/rajaneesh/z"):
            with self.subTest(branch=branch):
                self.assertTrue(self.manager.can_touch_branch(branch))
        for branch in ("main", "feature/johan-test", "feature/suma/x", "release/1.0", "feature/rajaneeshx/y"):
            with self.subTest(branch=branch):
                self.assertFalse(self.manager.can_touch_branch(branch))

    def test_main_is_denied_at_submission(self):
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(self.manager, "main", "docs", None)

    def test_a_repair_diff_touching_the_pipeline_is_refused_at_submission(self):
        with self.assertRaises(AuthorizationError):
            AuthorizationPolicy.check_submit_task(self.manager, "feature/rajaneesh/x", "code", ["tools/pipeline/bridge.py"])

    def test_authorization_fails_closed_without_modules(self):
        empty = DeveloperEntry(developer_id="empty", developer_name="E", github_username="e-gh", role="developer",
                               status="active", public_key_ed25519=KEY, assigned_modules=(), allowed_branches=("feature/*",))
        self.assertFalse(empty.can_touch_file("docs/a.md"))


class ExistingBehaviourUnchangedTest(unittest.TestCase):
    def test_a_docs_only_developer_still_gets_only_docs(self):
        dev = _developer_docs_only()
        self.assertTrue(dev.can_touch_file("docs/a.md"))
        self.assertFalse(dev.can_touch_file("frontend/a.tsx"))
        self.assertFalse(dev.can_touch_file("README.md"))
        self.assertFalse(dev.can_touch_file("tools/pipeline/bridge.py"))

    def test_owner_wildcard_no_longer_reaches_the_control_plane(self):
        owner = DeveloperEntry(developer_id="owner", developer_name="O", github_username="o-gh", role="project_owner",
                               status="active", public_key_ed25519=KEY, assigned_modules=("*",), allowed_branches=("*",))
        self.assertTrue(owner.can_touch_file("frontend/a.tsx"))
        self.assertFalse(owner.can_touch_file("tools/pipeline/bridge.py"))


if __name__ == "__main__":
    unittest.main()
