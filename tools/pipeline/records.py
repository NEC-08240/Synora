"""Job-record storage for one records directory: atomic writes, safe reads, and single ownership.

Writes go to a unique temp file, are flushed to disk, then replace the record in one step,
so a reader never sees half a record. Read-modify-write runs under one lock.

Ownership uses an OS file lock on .owner.lock. The OS releases it when the process exits,
even after a crash, so a leftover file never blocks a new owner and PIDs are never compared.
"""

import json
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

OWNER_LOCK_NAME = ".owner.lock"
RETRY_ATTEMPTS = 20
RETRY_DELAY_SECONDS = 0.05
TEMP_NAME_PATTERN = re.compile(r"([0-9a-f-]{36})\.json\..+\.tmp")

# Process-wide. Serializes read-modify-write of records across threads in this server.
_WRITE_LOCK = threading.RLock()


class RecordCorrupt(Exception):
    """A record file exists but does not hold a valid job record."""


class OwnerLockError(RuntimeError):
    """Another live process owns this records directory."""


def canonical_job_id(job_id):
    try:
        parsed = str(uuid.UUID(str(job_id)))
    except ValueError:
        raise ValueError(f"Invalid job ID: {job_id!r}") from None
    if parsed != str(job_id):
        raise ValueError(f"Invalid job ID: {job_id!r}")
    return parsed


def _now():
    return datetime.now(timezone.utc).isoformat()


def _retry(operation):
    """Windows can refuse a replace or read while another handle has the file open. Retry briefly."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return operation()
        except PermissionError:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY_SECONDS)


def _write_atomic(path, record):
    text = json.dumps(record, indent=2)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _retry(lambda: os.replace(temp_name, path))
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


class RecordStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, job_id):
        return self.directory / f"{canonical_job_id(job_id)}.json"

    def ids(self):
        """Job IDs of every record file with a canonical name. Other files are ignored."""
        if not self.directory.exists():
            return []
        found = []
        for path in self.directory.glob("*.json"):
            try:
                found.append(canonical_job_id(path.stem))
            except ValueError:
                continue
        return sorted(found)

    def read(self, job_id):
        path = self._path(job_id)
        try:
            text = _retry(lambda: path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(f"Job {job_id} not found.") from None
        try:
            record = json.loads(text)
        except json.JSONDecodeError as err:
            raise RecordCorrupt(f"Record {path.name} is not valid JSON: {err}") from None
        if not isinstance(record, dict) or record.get("job_id") != job_id:
            raise RecordCorrupt(f"Record {path.name} does not describe its own job.")
        return record

    def write_new(self, record):
        with _WRITE_LOCK:
            self.directory.mkdir(parents=True, exist_ok=True)
            _write_atomic(self._path(record["job_id"]), record)

    def update(self, job_id, mutate):
        """Read, change, and write one record under the lock.

        mutate(record) returns the fields to set. If it raises, nothing is written.
        """
        with _WRITE_LOCK:
            record = self.read(job_id)
            changes = mutate(record) or {}
            if 'developer_id' in changes and record.get('developer_id') is not None:
                if changes['developer_id'] != record['developer_id']:
                    raise ValueError('developer_id is immutable once set')
            record.update(changes, updated_at=_now())
            _write_atomic(self._path(job_id), record)
            return record

    def remove_temp_files(self):
        """Delete temp files left by interrupted writes. Only files matching our temp-name pattern."""
        if not self.directory.exists():
            return 0
        removed = 0
        for path in self.directory.glob("*.tmp"):
            if TEMP_NAME_PATTERN.fullmatch(path.name):
                path.unlink(missing_ok=True)
                removed += 1
        return removed


def _lock_first_byte(fd):
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_first_byte(fd):
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def read_owner_note(directory):
    """Who holds the lock, as written by the owner. Read from byte 1 on, which is never locked."""
    path = Path(directory) / OWNER_LOCK_NAME
    try:
        with open(path, "rb") as handle:
            handle.seek(1)
            return handle.read().decode("utf-8", errors="replace").strip() or "unknown owner"
    except OSError:
        return "unknown owner"


class DirectoryOwner:
    """Exclusive ownership of one records directory for the life of this process."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / OWNER_LOCK_NAME
        self._fd = None

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            _lock_first_byte(fd)
        except OSError as err:
            os.close(fd)
            raise OwnerLockError(
                f"Another bridge server already owns {self.directory} ({read_owner_note(self.directory)}). "
                "Stop that server before starting this one."
            ) from err
        os.ftruncate(fd, 1)
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, f"pid={os.getpid()} started={_now()}\n".encode("utf-8"))
        self._fd = fd
        return self

    def release(self):
        if self._fd is None:
            return
        try:
            _unlock_first_byte(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None

    def holds(self, directory):
        """True only while this owner holds the lock on the given directory."""
        return self._fd is not None and self.directory == Path(directory)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc_info):
        self.release()
