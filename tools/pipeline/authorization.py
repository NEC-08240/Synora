# Authorization policy for Synora Agent Bridge
import re
from typing import Optional, Sequence

from .team_registry import DeveloperEntry

SAFE_REF_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*(?:/[a-zA-Z0-9][a-zA-Z0-9_-]*)*\Z')

class AuthorizationError(PermissionError):
    pass

class AuthorizationPolicy:
    @staticmethod
    def check_submit_task(developer: DeveloperEntry, branch: str, task_type: str, changed_files: Optional[Sequence[str]] = None) -> None:
        if not developer.is_active():
            raise AuthorizationError(f'Developer {developer.developer_id!r} is {developer.status}.')

        if not branch or not isinstance(branch, str) or len(branch.strip()) > 255 or not SAFE_REF_PATTERN.match(branch):
            raise AuthorizationError(f'Invalid branch format or illegal characters in branch: {branch!r}.')

        if not developer.can_touch_branch(branch):
            raise AuthorizationError(
                f'Developer {developer.developer_id!r} is not authorized for branch {branch!r}. '
                f'Allowed patterns: {developer.allowed_branches}'
            )

        if changed_files:
            for file_path in changed_files:
                if not developer.can_touch_file(file_path):
                    raise AuthorizationError(
                        f'Developer {developer.developer_id!r} is not authorized to touch file {file_path!r}. '
                        f'Assigned modules: {developer.assigned_modules}'
                    )

    @staticmethod
    def check_job_access(developer: DeveloperEntry, job_record: dict, action: str = 'read') -> None:
        if developer.is_owner():
            return
        job_dev = job_record.get('developer_id')
        if job_dev is not None and job_dev != developer.developer_id:
            raise AuthorizationError(
                f'Developer {developer.developer_id!r} cannot {action} job {job_record.get('job_id')!r} '
                f'owned by {job_dev!r}.'
            )

    @staticmethod
    def check_admin_action(developer: DeveloperEntry, action_name: str) -> None:
        if not developer.is_owner():
            raise AuthorizationError(
                f'Action {action_name!r} requires role project_owner, but caller has role {developer.role!r}.'
            )

AuthorizationEngine = AuthorizationPolicy
