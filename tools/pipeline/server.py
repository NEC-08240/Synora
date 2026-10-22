"""MCP server for the Synora agent bridge. Start it with: python -m tools.pipeline.server"""

import json
from typing import Optional

from mcp.server.mcpserver import MCPServer

from .bridge import Bridge

mcp = MCPServer(name="synora-bridge")
bridge = Bridge()

STATUS_FIELDS = (
    "job_id", "task_type", "status", "target_job_id", "created_at", "updated_at",
    "started_at", "finished_at", "error", "cleanup_error",
)


def _reply(data):
    return json.dumps(data, indent=2)


@mcp.tool()
def submit_task(
    task: str,
    task_type: str = "docs",
    working_dir: str = ".",
    target_job_id: Optional[str] = None,
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
        record = bridge.submit(task, task_type, working_dir, target_job_id)
    except ValueError as err:
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
    except (KeyError, ValueError) as err:
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
    except (KeyError, ValueError) as err:
        return _reply({"error": str(err)})
    return _reply(record)


def main():
    bridge.mark_interrupted()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
