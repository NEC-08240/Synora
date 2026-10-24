"""The merge policy must send anything it cannot confidently call routine to Johan.

Run: python -m unittest tools.pipeline.test_merge_policy -v
"""

import unittest

from .merge_policy import ESCALATE, MAX_FILES, ROUTINE, FileChange, classify, parse_raw

MODE = "100644"


def change(path, old=MODE, new=MODE, status="M"):
    return FileChange(path=path, old_mode=old, new_mode=new, status=status)


class RoutineChangesTest(unittest.TestCase):
    def test_frontend_prototype_and_ui_docs_are_routine(self):
        # Arrange
        changes = [change("frontend/src/App.tsx"), change("prototypes/faculty/index.html"),
                   change("docs/ui-design/page-inventory.md")]
        # Act
        decision = classify(changes, "const title = 'Dashboard';")
        # Assert
        self.assertEqual(decision.verdict, ROUTINE)
        self.assertEqual(decision.reasons, [])

    def test_new_routine_file_is_routine(self):
        decision = classify([change("frontend/src/Card.tsx", old="000000", status="A")], "export const Card = 1;")
        self.assertEqual(decision.verdict, ROUTINE)


class EscalationAssertions:
    def assertEscalates(self, changes, added_text="", needle=""):
        decision = classify(changes, added_text)
        self.assertEqual(decision.verdict, ESCALATE)
        if needle:
            self.assertTrue(any(needle in reason for reason in decision.reasons), decision.reasons)


class EscalationPathsTest(EscalationAssertions, unittest.TestCase):

    def test_github_workflows_escalate(self):
        self.assertEscalates([change(".github/workflows/ci.yml")], needle="outside routine")

    def test_codeowners_escalates(self):
        self.assertEscalates([change(".github/CODEOWNERS")])

    def test_agent_bridge_and_lead_code_escalate(self):
        self.assertEscalates([change("tools/pipeline/worker.py")])
        self.assertEscalates([change("tools/pipeline/lead_attach.py")])

    def test_architecture_docs_escalate(self):
        self.assertEscalates([change("docs/architecture/agent-bridge.md")])

    def test_database_and_backend_escalate(self):
        self.assertEscalates([change("database/schema.sql")])
        self.assertEscalates([change("backend/app.py")])

    def test_repository_root_files_escalate(self):
        self.assertEscalates([change("README.md")])
        self.assertEscalates([change(".gitignore")])

    def test_auth_admin_and_credential_names_escalate_even_under_routine_prefix(self):
        self.assertEscalates([change("frontend/src/auth/LoginForm.tsx")], needle="sensitive path component")
        self.assertEscalates([change("prototypes/faculty-admin-ui/index.html")], needle="'admin'")

    def test_secret_files_and_scripts_escalate(self):
        self.assertEscalates([change("frontend/.env.local")], needle="sensitive file type")
        self.assertEscalates([change("frontend/certs/server.key")], needle="sensitive file type")
        self.assertEscalates([change("frontend/scripts/deploy.sh")], needle="sensitive file type")

    def test_dependency_manifests_escalate(self):
        self.assertEscalates([change("frontend/package.json")], needle="dependency")
        self.assertEscalates([change("frontend/package-lock.json")], needle="dependency")


class FailClosedTest(EscalationAssertions, unittest.TestCase):
    def test_empty_change_list_escalates(self):
        self.assertEqual(classify([], "").verdict, ESCALATE)

    def test_too_many_files_escalate(self):
        changes = [change(f"frontend/src/file{index}.ts") for index in range(MAX_FILES + 1)]
        self.assertEqual(classify(changes, "").verdict, ESCALATE)

    def test_uppercase_routine_prefix_does_not_match(self):
        self.assertEscalates([change("Frontend/src/App.tsx")], needle="outside routine")

    def test_symlink_escalates_on_either_side(self):
        self.assertEscalates([change("frontend/link", new="120000", status="A")], needle="symlink")
        self.assertEscalates([change("frontend/link", old="120000", status="D")], needle="symlink")

    def test_submodule_escalates(self):
        self.assertEscalates([change("frontend/vendor", new="160000")], needle="submodule")

    def test_executable_file_escalates(self):
        self.assertEscalates([change("frontend/tool", new="100755")], needle="executable")

    def test_traversal_absolute_drive_and_backslash_paths_escalate(self):
        for path in ("frontend/../tools/x.py", "/etc/passwd", "C:/x.ts", "frontend\\src\\a.ts", "frontend/a\tb.ts"):
            with self.subTest(path=path):
                self.assertEqual(classify([change(path)], "").verdict, ESCALATE)


class CredentialContentTest(unittest.TestCase):
    def test_private_key_block_in_added_text_escalates(self):
        decision = classify([change("frontend/src/notes.md")], "-----BEGIN OPENSSH PRIVATE KEY-----")
        self.assertEqual(decision.verdict, ESCALATE)

    def test_labelled_password_assignment_escalates(self):
        decision = classify([change("frontend/src/config.ts")], "const password = 'hunter2hunter2';")
        self.assertEqual(decision.verdict, ESCALATE)

    def test_known_token_formats_escalate(self):
        for text in ("sk-ant-api03-abcdefghijklmnop", "ghp_abcdefghijklmnopqrstuvwxyz0123456789", "AKIAABCDEFGHIJKLMNOP"):
            with self.subTest(text=text):
                self.assertEqual(classify([change("frontend/src/a.ts")], text).verdict, ESCALATE)

    def test_ordinary_word_key_in_docs_is_routine(self):
        decision = classify([change("docs/ui-design/wireframes.md")], "Press the key to continue.")
        self.assertEqual(decision.verdict, ROUTINE)


class GitParsingTest(unittest.TestCase):
    def test_parse_raw_reads_modes_status_and_path(self):
        raw = (":000000 100644 0000000 1111111 A\0frontend/new.ts\0"
               ":100644 100644 2222222 3333333 M\0docs/ui-design/a.md\0")
        changes = parse_raw(raw)
        self.assertEqual(changes, [
            FileChange("frontend/new.ts", "000000", "100644", "A"),
            FileChange("docs/ui-design/a.md", "100644", "100644", "M"),
        ])

    def test_rename_source_outside_routine_is_still_seen(self):
        # --no-renames reports the deletion of the old path, so moving a file out of a sensitive folder escalates.
        raw = ":100644 000000 1111111 0000000 D\0tools/pipeline/worker.py\0" \
              ":000000 100644 0000000 2222222 A\0frontend/worker.py\0"
        decision = classify(parse_raw(raw), "")
        self.assertEqual(decision.verdict, ESCALATE)
        self.assertTrue(any("tools/pipeline/worker.py" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()
