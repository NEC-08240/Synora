"""Cross-process mutex for the persistent Engineering Lead session.

One Claude session must have one active user at a time: a Worker-driven turn or Johan's interactive attach.
The lock is an OS file lock, so the operating system releases it when the holder exits, including when it
is killed. A crashed holder therefore cannot block the Lead forever.
"""

import os
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

POLL_SECONDS = 0.05


class LeadBusy(RuntimeError):
    """Another process holds the Lead session."""


class LeadMutex:
    def __init__(self, path, timeout: float = 60.0):
        self.path = Path(path)
        self.timeout = timeout
        self._handle = None

    def acquire(self, timeout: float):
        if self._handle is not None:
            raise RuntimeError("This LeadMutex is already held by this object.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock(handle)
                self._handle = handle
                return
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise LeadBusy(f"The Lead session is in use by another turn or an attached terminal (waited {timeout:g} s).") from None
                time.sleep(POLL_SECONDS)

    def release(self):
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        self.acquire(timeout=self.timeout)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _lock(handle):
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
