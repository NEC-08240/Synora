"""The Lead mutex must serialize processes, and a killed holder must not leave the lock held.

Run: python -m unittest tools.pipeline.test_lead_mutex -v
"""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from .lead_mutex import LeadBusy, LeadMutex

HOLDER = (
    "import sys, time\n"
    "from tools.pipeline.lead_mutex import LeadMutex\n"
    "m = LeadMutex(sys.argv[1])\n"
    "m.acquire(timeout=5)\n"
    "print('HELD', flush=True)\n"
    "time.sleep(60)\n"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


class LeadMutexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "lead.lock"

    def tearDown(self):
        self._tmp.cleanup()

    def test_second_acquire_in_same_process_times_out_while_first_is_held(self):
        first = LeadMutex(self.path)
        second = LeadMutex(self.path)
        first.acquire(timeout=1)
        try:
            with self.assertRaises(LeadBusy):
                second.acquire(timeout=0.3)
        finally:
            first.release()

    def test_lock_is_available_again_after_release(self):
        first = LeadMutex(self.path)
        second = LeadMutex(self.path)
        first.acquire(timeout=1)
        first.release()
        second.acquire(timeout=1)
        second.release()

    def test_context_manager_releases_on_exception(self):
        with self.assertRaises(ValueError):
            with LeadMutex(self.path):
                raise ValueError("turn failed")
        other = LeadMutex(self.path)
        other.acquire(timeout=1)
        other.release()

    def test_other_process_is_blocked_while_holder_runs(self):
        holder = subprocess.Popen(
            [sys.executable, "-B", "-c", HOLDER, str(self.path)],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "HELD")
            with self.assertRaises(LeadBusy):
                LeadMutex(self.path).acquire(timeout=0.5)
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()

    def test_lock_is_freed_when_holder_process_is_killed(self):
        holder = subprocess.Popen(
            [sys.executable, "-B", "-c", HOLDER, str(self.path)],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, text=True,
        )
        self.assertEqual(holder.stdout.readline().strip(), "HELD")
        holder.kill()
        holder.wait()
        holder.stdout.close()
        time.sleep(0.2)
        survivor = LeadMutex(self.path)
        survivor.acquire(timeout=3)
        survivor.release()


if __name__ == "__main__":
    unittest.main()
