"""Worker-local budget: how many jobs run, how often, and how much disk they may use.

The limits come only from trusted local configuration. Job payloads cannot change them, and the
Gateway has no path to the state file. Counts are written before a job starts, so a crash cannot
reset them. Anything the budget cannot read or measure is refused, not assumed to be fine.
"""

import json
import os
import threading
import time
from pathlib import Path

DEFAULT_JOBS_PER_WINDOW = 10
DEFAULT_JOBS_PER_DAY = 50
DAY_SECONDS = 86400
DEFAULT_WINDOW_SECONDS = 3600
DEFAULT_MAX_DISK_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_WORKTREES = 2
STATE_FILE_NAME = 'worker_budget.json'


class BudgetExceeded(RuntimeError):
    """The Worker refuses the job. The message is short and safe to send back to the Gateway."""


def _tree_bytes(path):
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path, onerror=_raise):
        for name in files:
            total += os.lstat(os.path.join(root, name)).st_size
    return total


def _raise(err):
    raise OSError(f'cannot measure {err.filename}: {err.strerror}')


class WorkerBudget:
    def __init__(
        self,
        state_dir,
        jobs_per_window=DEFAULT_JOBS_PER_WINDOW,
        window_seconds=DEFAULT_WINDOW_SECONDS,
        jobs_per_day=DEFAULT_JOBS_PER_DAY,
        max_disk_bytes=DEFAULT_MAX_DISK_BYTES,
        max_worktrees=DEFAULT_MAX_WORKTREES,
        clock=time.time,
    ):
        for name, value in (('jobs_per_window', jobs_per_window), ('window_seconds', window_seconds), ('jobs_per_day', jobs_per_day),
                            ('max_disk_bytes', max_disk_bytes), ('max_worktrees', max_worktrees)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f'{name} must be a positive integer.')
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / STATE_FILE_NAME
        self.jobs_per_window = jobs_per_window
        self.jobs_per_day = jobs_per_day
        self.window_seconds = window_seconds
        self.max_disk_bytes = max_disk_bytes
        self.max_worktrees = max_worktrees
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False

    # ---- counters ----------------------------------------------------------

    def _load(self):
        if not self.state_path.exists():
            return []
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            stamps = data['starts']
            if not isinstance(stamps, list) or not all(isinstance(s, (int, float)) for s in stamps):
                raise ValueError('wrong shape')
            return [float(s) for s in stamps]
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise BudgetExceeded('Worker budget state is unreadable; refusing jobs until it is repaired.') from err

    def _save(self, stamps):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'starts': stamps}), encoding='utf-8')
        os.replace(temp, self.state_path)

    # ---- measurements ------------------------------------------------------

    def _disk_bytes(self):
        try:
            return _tree_bytes(self.state_dir / 'jobs') + _tree_bytes(self.state_dir / 'worktrees')
        except OSError as err:
            raise BudgetExceeded('Worker disk usage cannot be measured; refusing jobs.') from err

    def _worktree_count(self):
        folder = self.state_dir / 'worktrees'
        try:
            return sum(1 for entry in folder.iterdir()) if folder.exists() else 0
        except OSError as err:
            raise BudgetExceeded('Worker worktrees cannot be counted; refusing jobs.') from err

    # ---- admission ---------------------------------------------------------

    def admit(self):
        """Reserve a job slot. Raises BudgetExceeded when any limit would be crossed."""
        with self._lock:
            if self._running:
                raise BudgetExceeded('A job is already running on this Worker.')
            now = self._clock()
            stamps = [s for s in self._load() if now - s < max(self.window_seconds, DAY_SECONDS)]
            if sum(1 for s in stamps if now - s < self.window_seconds) >= self.jobs_per_window:
                raise BudgetExceeded(
                    f'Rate limit reached: {self.jobs_per_window} jobs per {self.window_seconds} seconds.'
                )
            if sum(1 for s in stamps if now - s < DAY_SECONDS) >= self.jobs_per_day:
                raise BudgetExceeded(f'Daily limit reached: {self.jobs_per_day} jobs per day.')
            if self._disk_bytes() > self.max_disk_bytes:
                raise BudgetExceeded('Worker disk budget is exceeded; refusing jobs.')
            if self._worktree_count() >= self.max_worktrees:
                raise BudgetExceeded('Too many Worker worktrees exist; refusing jobs.')
            stamps.append(now)
            self._save(stamps)
            self._running = True

    def finish(self):
        # Released without the lock so a failure elsewhere can never leave the slot held.
        self._running = False
