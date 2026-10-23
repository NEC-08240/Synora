# Tests for Git Ownership Invariants (Section 29)
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from .bridge import Bridge, REVIEW_TOOLS
from .worker import OutboundWorker


class FakeClaude:
    def __init__(self, write=None):
        self.write = write

    def __call__(self, prompt, cwd, tools, permission_mode):
        if self.write and tools != REVIEW_TOOLS:
            p = Path(cwd) / self.write
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# written by Claude\n', encoding='utf-8')
        payload = {'subtype': 'success', 'is_error': False, 'result': 'Done'}
        return 0, json.dumps(payload), ''


class TestGitOwnership(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name

        # Initialize a real git repo
        subprocess.run(['git', 'init'], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Synora Dev'], cwd=self.repo_dir, check=True)
        subprocess.run(['git', 'config', 'user.email', 'dev@synora.internal'], cwd=self.repo_dir, check=True)

        # Create initial commit
        readme_path = os.path.join(self.repo_dir, 'README.md')
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write('# Synora Base Repo\n')
        subprocess.run(['git', 'add', 'README.md'], cwd=self.repo_dir, check=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=self.repo_dir, check=True)

        res = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.repo_dir, check=True, capture_output=True, text=True)
        self.initial_head = res.stdout.strip()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_worker_and_bridge_have_no_push_merge_or_commit_methods(self):
        worker = OutboundWorker(worker_id='worker-git-1')
        bridge = Bridge(repo_root=self.repo_dir)

        forbidden_methods = ['git_commit', 'commit', 'git_push', 'push', 'git_merge', 'merge']
        for method in forbidden_methods:
            self.assertFalse(hasattr(worker, method), f'Worker must not have {method}')
            self.assertFalse(hasattr(bridge, method), f'Bridge must not have {method}')

    def test_worker_execution_does_not_advance_git_head_or_create_commits(self):
        claude_runner = FakeClaude(write='docs/agent-bridge/summary.md')
        bridge = Bridge(repo_root=self.repo_dir, runner=claude_runner)
        worker = OutboundWorker(worker_id='worker-git-1', bridge=bridge)

        # Execute docs job in bridge
        record = bridge.create(task='Add summary doc', task_type='docs')
        job_id = record['job_id']

        bridge.execute(job_id)
        result = bridge.get(job_id)

        # Invariant 1: Result must contain the diff for human developer review
        self.assertIn('diff', result)
        self.assertTrue(len(result['diff']) > 0)
        self.assertIn('summary.md', result['diff'])

        # Invariant 2: Base repository HEAD has NOT moved
        head_after = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(head_after, self.initial_head, 'Base git HEAD must remain unchanged.')

        # Invariant 3: Base repository git log has exactly 1 commit (the initial one)
        log_res = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(int(log_res), 1, 'No new commits must be created on base repository.')


if __name__ == '__main__':
    unittest.main()
