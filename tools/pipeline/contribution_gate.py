# Contribution Gate validator for Synora Agent Bridge
import re
from typing import Dict, List, Optional

from .team_registry import DeveloperEntry

DIFF_HEADER_PATTERN = re.compile(r'^diff --git a/(.+) b/(.+)$', re.MULTILINE)
OLD_FILE_PATTERN = re.compile(r'^--- a/(.+)$', re.MULTILINE)
NEW_FILE_PATTERN = re.compile(r'^\+\+\+ b/(.+)$', re.MULTILINE)

class ContributionGateError(ValueError):
    pass

def extract_files_from_diff(diff_text: str) -> List[str]:
    files = set()
    for m in DIFF_HEADER_PATTERN.finditer(diff_text):
        files.add(m.group(2).strip())
    for m in NEW_FILE_PATTERN.finditer(diff_text):
        target = m.group(1).strip()
        if target != '/dev/null':
            files.add(target)
    for m in OLD_FILE_PATTERN.finditer(diff_text):
        target = m.group(1).strip()
        if target != '/dev/null':
            files.add(target)

    cleaned = []
    for f in sorted(files):
        norm = f.replace(chr(92), '/').lstrip('/')
        parts = norm.split('/')
        if '..' in parts:
            raise ContributionGateError(f'Path traversal detected in diff file: {f!r}')
        cleaned.append(norm)
    return cleaned

class ContributionGate:
    @staticmethod
    def validate(
        developer: DeveloperEntry,
        task: str,
        task_type: str,
        branch: str,
        base_commit: str,
        is_repair: bool = False,
        developer_diff: str = '',
        local_evidence: Optional[Dict] = None,
    ) -> Dict:
        if not developer.is_active():
            raise ContributionGateError(f'Developer {developer.developer_id!r} is {developer.status}.')

        if not task or len(task.strip()) < 10:
            raise ContributionGateError('Task description must be at least 10 characters long.')

        if not branch or not branch.strip():
            raise ContributionGateError('Branch name must be specified.')

        if not developer.can_touch_branch(branch):
            raise ContributionGateError(
                f'Developer {developer.developer_id!r} is not authorized for branch {branch!r}.'
            )

        if not base_commit or len(base_commit.strip()) < 7:
            raise ContributionGateError('Valid base_commit ref or SHA must be provided.')

        changed_files = []
        if is_repair:
            if not developer_diff or not developer_diff.strip():
                raise ContributionGateError(
                    'Empty diff rejected: Claude repair requires prior implementation attempt by the developer.'
                )

            changed_files = extract_files_from_diff(developer_diff)
            if not changed_files:
                raise ContributionGateError('Diff contains no identifiable file changes.')

            for f in changed_files:
                if not developer.can_touch_file(f):
                    raise ContributionGateError(
                        f'Scope violation: file {f!r} is outside assigned modules {developer.assigned_modules}.'
                    )

            if not local_evidence or not isinstance(local_evidence, dict):
                raise ContributionGateError('Repair requests require local_evidence documenting the failure.')

            exit_code = local_evidence.get('exit_code')
            if exit_code is None or exit_code == 0:
                raise ContributionGateError(
                    'Local evidence exit_code must be non-zero for repair requests. '
                    'If local tests pass, request review instead of repair.'
                )

            failure_output = str(local_evidence.get('failure_output', '')).strip()
            if not failure_output:
                raise ContributionGateError('Local evidence must include non-empty failure_output.')

        return {
            'status': 'ACCEPTED',
            'developer_id': developer.developer_id,
            'branch': branch.strip(),
            'base_commit': base_commit.strip(),
            'is_repair': is_repair,
            'changed_files': changed_files,
            'file_count': len(changed_files),
        }
