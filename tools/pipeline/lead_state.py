"""Persistent state of the Engineering Lead Claude session, kept in the Worker's local state folder.

The session ID is an identifier, not a credential, but it is still kept local: it is never sent to the
Gateway or written to tracked files. Every write is atomic (temporary file, then replace), so a crash cannot
leave a half-written file. Anything unexpected fails closed: a corrupt file, an unknown schema, an interrupted
creation, a session mismatch, or a job that is already known to the Lead.
"""

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .audit import redact_secret_values

SCHEMA = 1
STATE_UNINITIALIZED = "UNINITIALIZED"
STATE_CREATING = "CREATING"
STATE_ACTIVE = "ACTIVE"
STATE_BROKEN = "BROKEN"
KNOWN_STATES = {STATE_UNINITIALIZED, STATE_CREATING, STATE_ACTIVE, STATE_BROKEN}

JOB_PENDING = "PENDING"
JOB_DONE = "DONE"
JOB_FAILED = "FAILED"
JOB_INTERRUPTED = "INTERRUPTED"

MAX_STORED_TEXT_CHARS = 8000  # matches the bridge's MAX_RESULT_CHARS
MAX_EVIDENCE_ITEMS = 20


class LeadStateError(RuntimeError):
    """The Lead state does not allow the requested action. The Lead stops rather than guessing."""


class LeadState:
    def __init__(self, path: Path, data: Dict[str, Any]):
        self.path = Path(path)
        self._data = data

    # ---- loading and saving -------------------------------------------------

    @classmethod
    def load(cls, path) -> "LeadState":
        path = Path(path)
        if not path.exists():
            return cls(path, _empty())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise LeadStateError(f"Lead state file is unreadable; admin action required ({err.__class__.__name__}).") from None
        _validate(data)
        return cls(path, data)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    # ---- read accessors -------------------------------------------------------

    @property
    def status(self) -> str:
        return self._data["state"]

    @property
    def session_id(self) -> Optional[str]:
        return self._data["session_id"]

    @property
    def turns(self) -> int:
        return self._data["turns"]

    @property
    def cumulative_cost_usd(self) -> float:
        return self._data["cumulative_cost_usd"]

    def job_status(self, job_id: str) -> Optional[str]:
        job = self._data["jobs"].get(job_id)
        return job["status"] if job else None

    def stored_outcome(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._data["jobs"].get(job_id)
        if job and job["status"] == JOB_DONE:
            return job["outcome"]
        return None

    def ensure_usable(self, expected_session_id: Optional[str] = None):
        if self.status == STATE_CREATING:
            raise LeadStateError("A Lead session creation was interrupted; admin action required. Nothing was created or resumed.")
        if self.status == STATE_BROKEN:
            raise LeadStateError("The Lead session is marked BROKEN; admin action required. Turns are refused.")
        if self.status != STATE_ACTIVE:
            raise LeadStateError("The Lead session has not been created yet.")
        if expected_session_id is not None and expected_session_id != self.session_id:
            raise LeadStateError("The configured Lead session ID does not match the stored one. Refusing to continue.")

    # ---- session lifecycle ----------------------------------------------------

    def begin_create(self, session_id: str):
        if self.status != STATE_UNINITIALIZED:
            raise LeadStateError("A Lead session already exists; it is never silently replaced.")
        _require_uuid(session_id)
        self._data.update(state=STATE_CREATING, session_id=session_id)
        self._save()

    def mark_active(self, session_id: str):
        if self.status != STATE_CREATING or session_id != self.session_id:
            raise LeadStateError("Lead session activation does not match the pending creation.")
        self._data["state"] = STATE_ACTIVE
        self._save()

    def mark_broken(self, reason: str, evidence: Dict[str, Any]):
        self._data["state"] = STATE_BROKEN
        self._data["broken_reason"] = _clean(reason)
        self._data["evidence"] = (self._data.get("evidence", []) + [_clean(evidence)])[-MAX_EVIDENCE_ITEMS:]
        self._save()

    # ---- jobs -----------------------------------------------------------------

    def begin_turn(self, job_id: str, developer_id: str):
        self.ensure_usable()
        if job_id in self._data["jobs"]:
            raise LeadStateError(f"Job {job_id} was already submitted to the Lead; it is not run again.")
        self._data["jobs"][job_id] = {"status": JOB_PENDING, "developer_id": developer_id, "outcome": None}
        self._save()

    def finish_turn(self, job_id: str, outcome: Dict[str, Any], cost_usd: float):
        job = self._pending(job_id)
        job.update(status=JOB_DONE, outcome=_clean(outcome))
        self._data["turns"] += 1
        self._data["cumulative_cost_usd"] = round(self._data["cumulative_cost_usd"] + float(cost_usd), 8)
        self._save()

    def fail_turn(self, job_id: str, error: str):
        job = self._pending(job_id)
        job.update(status=JOB_FAILED, outcome={"status": "FAILED", "error": _clean(error)})
        self._save()

    def mark_interrupted_jobs(self):
        """Run at startup: a job still PENDING was cut off mid-turn. It is recorded, never run again."""
        interrupted = []
        for job_id, job in self._data["jobs"].items():
            if job["status"] == JOB_PENDING:
                job.update(status=JOB_INTERRUPTED, outcome={"status": "FAILED", "error": "Interrupted while the Lead was running; not run again."})
                interrupted.append(job_id)
        if interrupted:
            self._save()
        return interrupted

    def _pending(self, job_id: str) -> Dict[str, Any]:
        job = self._data["jobs"].get(job_id)
        if not job or job["status"] != JOB_PENDING:
            raise LeadStateError(f"Job {job_id} is not an active Lead turn.")
        return job


def _empty() -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "state": STATE_UNINITIALIZED,
        "session_id": None,
        "turns": 0,
        "cumulative_cost_usd": 0.0,
        "jobs": {},
        "evidence": [],
    }


def _validate(data: Any):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise LeadStateError("Lead state file has an unknown schema; admin action required.")
    if data.get("state") not in KNOWN_STATES:
        raise LeadStateError("Lead state file has an unknown state; admin action required.")
    if data.get("session_id") is not None:
        _require_uuid(data["session_id"])
    if not isinstance(data.get("jobs"), dict) or not isinstance(data.get("turns"), int):
        raise LeadStateError("Lead state file is malformed; admin action required.")
    if not isinstance(data.get("cumulative_cost_usd"), (int, float)):
        raise LeadStateError("Lead state file is malformed; admin action required.")


def _require_uuid(value):
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise LeadStateError("The Lead session ID must be a UUID.") from None
    if str(uuid.UUID(str(value))) != str(value).lower():
        raise LeadStateError("The Lead session ID must be a canonical UUID.")


_ASSIGNED_CREDENTIAL = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[^\s,;]{8,}")


def redact_lead_text(text: str) -> str:
    """Known credential formats, plus a narrow rule for `password=…`, `api_key: …` style assignments.

    Ordinary words such as "the token count" are kept. Arbitrary unlabelled secrets are not detected.
    """
    return _ASSIGNED_CREDENTIAL.sub(lambda m: f"{m.group(1)}=[REDACTED]", redact_secret_values(text))


def _clean(value: Any) -> Any:
    """Redact secret-looking text and bound every string, recursively."""
    if isinstance(value, str):
        return redact_lead_text(value)[:MAX_STORED_TEXT_CHARS]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value
