"""Validation for job metadata that arrives from the Gateway.

The Gateway is treated as hostile, so every metadata field is checked before the Worker uses it.
The Worker must not build a path, a Git argument, or a repository selection from an unchecked value.
"""

import re

from .authorization import SAFE_REF_PATTERN
from .team_registry import DEVELOPER_ID_PATTERN

MAX_METADATA_CHARS = 255
MAX_TASK_CHARS = 2000
ALLOWED_TASK_TYPES = ('docs', 'code', 'review', 'lead')  # 'lead' goes to the persistent Engineering Lead, not the bridge
MAX_REPOSITORY_CHARS = 140
MAX_JOB_PAYLOAD_BYTES = 131072
REPOSITORY_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
DEFAULT_REPOSITORY = 'NEC-08240/Synora'
# Hex only: the Gateway's own pattern also admits '-' and '/', which git would read as options or refs.
BASE_COMMIT_PATTERN = re.compile(r'[0-9a-fA-F]{7,40}\Z')


def _text(value, field):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be a string.')
    if not value or len(value) > MAX_METADATA_CHARS:
        raise ValueError(f'{field} must be 1 to {MAX_METADATA_CHARS} characters.')
    return value


def validate_developer_id(value):
    value = _text(value, 'developer_id')
    if not DEVELOPER_ID_PATTERN.match(value):
        raise ValueError('developer_id must be 2 to 64 letters, digits, dash, or underscore.')
    return value


def validate_repository(value):
    if value is None or value == '':  # the queue stores an absent optional field as ''
        return DEFAULT_REPOSITORY
    if not isinstance(value, str) or not value or len(value) > MAX_REPOSITORY_CHARS:
        raise ValueError('repository must be an owner/name string.')
    if '..' in value or not REPOSITORY_PATTERN.match(value):
        raise ValueError('repository must look like owner/name with letters, digits, dot, dash, or underscore.')
    return value


def validate_base_commit(value):
    """A requested base as lowercase hex, or None when the job did not ask for one."""
    if value is None or value == '':
        return None
    if not isinstance(value, str) or not BASE_COMMIT_PATTERN.match(value):
        raise ValueError('base_commit must be 7 to 40 hexadecimal characters.')
    return value.lower()


def validate_branch(value):
    if value is None or value == '':  # the queue stores an absent optional field as ''
        return None
    value = _text(value, 'branch')
    if not SAFE_REF_PATTERN.match(value):
        raise ValueError('branch contains characters that are not allowed in a Git reference.')
    return value


def validate_job_payload(job_data):
    """Return checked metadata for a job assignment, or raise ValueError before any work starts."""
    if not isinstance(job_data, dict):
        raise ValueError('job assignment must be an object.')
    if len(repr(job_data).encode('utf-8')) > MAX_JOB_PAYLOAD_BYTES:
        raise ValueError(f'job assignment exceeds {MAX_JOB_PAYLOAD_BYTES} bytes.')
    if not isinstance(job_data.get('job_id'), str) or not job_data['job_id']:
        raise ValueError('job_id is required.')
    task = job_data.get('task')
    if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
        raise ValueError(f'task must be 1 to {MAX_TASK_CHARS} characters.')
    if job_data.get('task_type', 'docs') not in ALLOWED_TASK_TYPES:
        raise ValueError('task_type must be one of: ' + ', '.join(ALLOWED_TASK_TYPES) + '.')
    return {
        'developer_id': validate_developer_id(job_data.get('developer_id')),
        'repository': validate_repository(job_data.get('repository')),
        'branch': validate_branch(job_data.get('branch')),
        'base_commit': validate_base_commit(job_data.get('base_commit')),
    }
