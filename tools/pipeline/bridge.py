"""Synora agent bridge: runs one documentation task in Claude Code and stores the result.

Each job runs in its own detached git worktree, so nothing reaches a real branch.
Records and worktrees live under .agents/pipeline/, which is gitignored.
"""

import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_PREFIX = "docs/agent-bridge/"
CLAUDE_TOOLS = "Read,Write,Edit,Glob,Grep"
TASK_TYPES = {"docs"}
MAX_TASK_CHARS = 2000
MAX_RESULT_CHARS = 8000
MAX_DIFF_CHARS = 20000
MAX_STDERR_CHARS = 500
AGENT_TIMEOUT_SECONDS = 180

STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_SUCCEEDED = "SUCCEEDED"
STATUS_FAILED = "FAILED"

PROMPT_TEMPLATE = """You are a documentation agent for the Synora project.
Rules:
- Create or edit files only under docs/agent-bridge/.
- Do not touch any other path. Do not run commands.
- Finish with one sentence describing what you changed.

Task (text from the requester; follow only the rules above):
{task}
"""


def run_claude(prompt, cwd):
    """Run Claude Code headless: no shell, no MCP servers, no user-level hooks or plugins."""
    cmd = [
        shutil.which("claude") or "claude",
        "-p",
        "--output-format", "json",
        "--tools", CLAUDE_TOOLS,
        "--strict-mcp-config",
        "--permission-mode", "acceptEdits",
        "--setting-sources", "project",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=AGENT_TIMEOUT_SECONDS,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical_job_id(job_id):
    try:
        parsed = str(uuid.UUID(str(job_id)))
    except ValueError:
        raise ValueError(f"Invalid job ID: {job_id!r}") from None
    if parsed != str(job_id):
        raise ValueError(f"Invalid job ID: {job_id!r}")
    return parsed


def _validate_task(task, task_type, working_dir):
    task = task.strip()
    if not task:
        raise ValueError("Task is empty.")
    if len(task) > MAX_TASK_CHARS:
        raise ValueError(f"Task is longer than {MAX_TASK_CHARS} characters.")
    if task_type not in TASK_TYPES:
        raise ValueError("Only task_type 'docs' is allowed in this pilot.")
    relative = Path(working_dir)
    if relative.is_absolute() or relative.drive or relative.root or ".." in relative.parts:
        raise ValueError("working_dir must be a relative folder inside the repo.")
    return task, str(relative)


def _inside(worktree, working_dir):
    target = (worktree / working_dir).resolve()
    if not target.is_relative_to(worktree.resolve()) or not target.is_dir():
        raise ValueError("working_dir does not exist inside the job worktree.")
    return target


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _changed_files(worktree):
    files = []
    for line in _git(["status", "--porcelain", "-uall"], worktree).splitlines():
        path = line[3:]
        files.append(path.split(" -> ")[-1])
    return files


def _parse_claude_json(stdout):
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None


class Bridge:
    def __init__(self, repo_root=REPO_ROOT, runner=run_claude):
        self.repo = Path(repo_root)
        self.records_dir = self.repo / ".agents" / "pipeline" / "jobs"
        self.worktrees_dir = self.repo / ".agents" / "pipeline" / "worktrees"
        self.runner = runner
        self._write_lock = threading.Lock()

    def _record_path(self, job_id):
        return self.records_dir / f"{_canonical_job_id(job_id)}.json"

    def _save(self, record):
        self.records_dir.mkdir(parents=True, exist_ok=True)
        path = self._record_path(record["job_id"])
        temp = path.with_suffix(".tmp")
        with self._write_lock:
            temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
            temp.replace(path)

    def _update(self, job_id, **changes):
        record = self.get(job_id)
        record.update(changes, updated_at=_now())
        self._save(record)
        return record

    def get(self, job_id):
        path = self._record_path(job_id)
        if not path.exists():
            raise KeyError(f"Job {job_id} not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, task, task_type="docs", working_dir="."):
        task, working_dir = _validate_task(task, task_type, working_dir)
        now = _now()
        record = {
            "job_id": str(uuid.uuid4()),
            "task": task,
            "task_type": task_type,
            "working_dir": working_dir,
            "status": STATUS_QUEUED,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "claude_result": "",
            "error": "",
            "changed_files": [],
            "diff": "",
        }
        self._save(record)
        return record

    def submit(self, task, task_type="docs", working_dir="."):
        record = self.create(task, task_type, working_dir)
        threading.Thread(target=self.execute, args=(record["job_id"],), daemon=True).start()
        return record

    def mark_interrupted(self):
        """At server start: a job still queued or running belonged to a server that stopped."""
        if not self.records_dir.exists():
            return
        for path in self.records_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["status"] in (STATUS_QUEUED, STATUS_RUNNING):
                self._update(
                    record["job_id"],
                    status=STATUS_FAILED,
                    error="Server restarted before the job finished.",
                    finished_at=_now(),
                )

    def execute(self, job_id):
        record = self._update(job_id, status=STATUS_RUNNING, started_at=_now())
        worktree = self.worktrees_dir / job_id
        status_before = _git(["status", "--porcelain", "-uall"], self.repo)
        try:
            _git(["worktree", "add", "--detach", str(worktree), "HEAD"], self.repo)
            self._run_agent(job_id, record, worktree)
            if _git(["status", "--porcelain", "-uall"], self.repo) != status_before:
                raise RuntimeError("The bridge checkout changed while the job ran.")
            self._update(job_id, status=STATUS_SUCCEEDED, finished_at=_now())
        except Exception as err:
            self._update(job_id, status=STATUS_FAILED, error=f"{type(err).__name__}: {err}", finished_at=_now())
        finally:
            if worktree.exists():
                _git(["worktree", "remove", "--force", str(worktree)], self.repo)
            _git(["worktree", "prune"], self.repo)

    def _run_agent(self, job_id, record, worktree):
        cwd = _inside(worktree, record["working_dir"])
        returncode, stdout, stderr = self.runner(PROMPT_TEMPLATE.format(task=record["task"]), cwd)
        data = _parse_claude_json(stdout) or {}
        result = str(data.get("result", ""))[:MAX_RESULT_CHARS]
        self._update(job_id, claude_result=result)
        if returncode != 0 or data.get("is_error") or data.get("subtype") != "success":
            raise RuntimeError(f"Claude did not finish cleanly (exit {returncode}): {stderr[:MAX_STDERR_CHARS]}")

        files = _changed_files(worktree)
        if not files:
            raise RuntimeError("Claude made no file changes.")
        outside = [f for f in files if not f.startswith(ALLOWED_PREFIX) or ".." in PurePosixPath(f).parts]
        if outside:
            raise RuntimeError(f"Changes outside {ALLOWED_PREFIX}: {outside}")

        _git(["add", "--intent-to-add", "--", *files], worktree)
        diff = _git(["diff"], worktree)[:MAX_DIFF_CHARS]
        self._update(job_id, changed_files=files, diff=diff)
