"""`admin_cli update-developer-scope` changes only a developer's modules and branches.

Identity, public key, role, status and the other developers' entries must be untouched.
Run: python -m unittest tools.pipeline.test_admin_scope_update -v
"""

import base64
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from .admin_cli import add_developer, update_developer_scope
from .team_registry import RegistryError, TeamRegistry


def _pub():
    key = ed25519.Ed25519PrivateKey.generate()
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()


class UpdateScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "team.json"
        self.key = _pub()
        self.other_key = _pub()
        add_developer(self.path, "rajaneesh", "Rajaneesh T V", "rajaneeshappu07-netizen", self.key,
                      modules=("docs/",), branches=("feature/rajaneesh/*",))
        add_developer(self.path, "johan-admin", "Johan", "StevefromSpace", self.other_key,
                      modules=("docs/",), branches=("feature/*",))

    def tearDown(self):
        self._tmp.cleanup()

    def test_only_modules_and_branches_change(self):
        update_developer_scope(self.path, "rajaneesh", modules=["docs/", "frontend/", "README.md"],
                               branches=["feature/rajaneesh/*", "fix/rajaneesh/*"])
        entry = TeamRegistry.load(self.path).get("rajaneesh")
        self.assertEqual(entry.assigned_modules, ("docs/", "frontend/", "README.md"))
        self.assertEqual(entry.allowed_branches, ("feature/rajaneesh/*", "fix/rajaneesh/*"))
        self.assertEqual(entry.public_key_ed25519, self.key)
        self.assertEqual(entry.role, "developer")
        self.assertEqual(entry.status, "active")
        self.assertEqual(entry.github_username, "rajaneeshappu07-netizen")
        self.assertEqual(entry.developer_name, "Rajaneesh T V")

    def test_other_developers_are_unchanged(self):
        before = TeamRegistry.load(self.path).get("johan-admin")
        update_developer_scope(self.path, "rajaneesh", modules=["frontend/"], branches=["feature/rajaneesh/*"])
        after = TeamRegistry.load(self.path).get("johan-admin")
        self.assertEqual(before, after)

    def test_unknown_developer_is_refused_and_the_file_is_unchanged(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(RegistryError):
            update_developer_scope(self.path, "nobody", modules=["docs/"], branches=["feature/*"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_glob_module_scopes_are_refused_and_the_file_is_unchanged(self):
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            update_developer_scope(self.path, "rajaneesh", modules=["frontend/*"], branches=["feature/rajaneesh/*"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_path_traversal_in_a_module_is_refused(self):
        with self.assertRaises(RegistryError):
            update_developer_scope(self.path, "rajaneesh", modules=["frontend/../tools/"], branches=["feature/rajaneesh/*"])

    def test_the_updated_file_still_loads_and_validates(self):
        update_developer_scope(self.path, "rajaneesh", modules=["docs/", "README.md"], branches=["feature/rajaneesh/*"])
        registry = TeamRegistry.load(self.path)
        self.assertEqual(len(registry.list_all()), 2)


if __name__ == "__main__":
    unittest.main()
