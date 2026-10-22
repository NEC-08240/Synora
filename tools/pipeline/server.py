"""MCP server for the Synora agent bridge. Start it with: python -m tools.pipeline.server

Environment (all optional):
    SYNORA_BRIDGE_REPO    repo root to use. Default: the checkout this file lives in.
    SYNORA_BRIDGE_GIT     full path to git. Default: PATH lookup.
    SYNORA_BRIDGE_CLAUDE  full path to the Claude Code executable. Default: PATH lookup.

Exit codes: 2 = a required executable was not found; 3 = another server owns the records directory.
"""

import json
import os
import sys
from typing import Optional

from mcp.server.mcpserver import MCPServer

from .bridge import REPO_ROOT, Bridge
from .executables import CLAUDE_ENV, GIT_ENV, ExecutableNotFound, resolve_executable
from .records import DirectoryOwner, OwnerLockError, RecordCorrupt

EXIT_MISSING_EXECUTABLE = 2
EXIT_RECORDS_OWNED = 3

STATUS_FIELDS = (
    "job_id", "developer_id", "repository", "branch", "task_type", "status", "target_job_id", "created_at", "updated_at",
    "started_at", "finished_at", "error", "cleanup_error",
)

mcp = MCPServer(name="synora-bridge")
bridge = Bridge(repo_root=os.environ.get("SYNORA_BRIDGE_REPO") or REPO_ROOT)


def _reply(data):
    return json.dumps(data, indent=2)


def _report(message):
    print(f"synora-bridge: {message}", file=sys.stderr)


@mcp.tool()
def submit_task(
    task: str,
    task_type: str = "docs",
    working_dir: str = ".",
    target_job_id: Optional[str] = None,
    developer_id: Optional[str] = None,
    repository: Optional[str] = None,
    branch: Optional[str] = None,
) -> str:
    """Start a Claude Code task. Returns a job_id to poll.

    Args:
        task: What to do. docs tasks write only under docs/agent-bridge/. code tasks write only under
              frontend/, backend/, database/, or tests/ and must pass verification. review tasks are read-only.
        task_type: One of "docs", "code", "review".
        working_dir: Relative folder inside the job worktree to start Claude in. Defaults to the repo root.
        target_job_id: Required for review tasks: the finished job to review.
    """
    try:
        record = bridge.submit(task, task_type, working_dir, target_job_id, developer_id=developer_id, repository=repository, branch=branch)
    except (ValueError, RuntimeError) as err:
        return _reply({"success": False, "error": str(err)})
    return _reply({"success": True, "job_id": record["job_id"], "status": record["status"]})


@mcp.tool()
def get_status(job_id: str) -> str:
    """Return the status of a job.

    Args:
        job_id: The job_id returned by submit_task.
    """
    try:
        record = bridge.get(job_id)
    except (KeyError, ValueError, RecordCorrupt) as err:
        return _reply({"error": str(err)})
    return _reply({field: record.get(field) for field in STATUS_FIELDS})


@mcp.tool()
def get_result(job_id: str) -> str:
    """Return the full record of a job: Claude result, changed files, diff, verification, and review.

    Args:
        job_id: The job_id returned by submit_task.
    """
    try:
        record = bridge.get(job_id)
    except (KeyError, ValueError, RecordCorrupt) as err:
        return _reply({"error": str(err)})
    return _reply(record)


def main():
    try:
        bridge.git = resolve_executable("git", GIT_ENV)
        bridge.claude = resolve_executable("claude", CLAUDE_ENV)
    except ExecutableNotFound as err:
        _report(str(err))
        sys.exit(EXIT_MISSING_EXECUTABLE)

    owner = DirectoryOwner(bridge.records_dir)
    try:
        owner.acquire()
    except OwnerLockError as err:
        _report(str(err))
        sys.exit(EXIT_RECORDS_OWNED)
    try:
        report = bridge.recover_abandoned(owner)
        for problem in report["problems"]:
            _report(problem)
        mcp.run(transport="stdio")
    finally:
        owner.release()


if __name__ == "__main__":
    main()
