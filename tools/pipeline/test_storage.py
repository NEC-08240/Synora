"""Tests for job-record storage and single-owner records directories. Run: python -m unittest tools.pipeline.test_storage -v"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from .records import (
    OWNER_LOCK_NAME,
    DirectoryOwner,
    OwnerLockError,
    RecordCorrupt,
    RecordStore,
    read_owner_note,
)


def _record(job_id=None, **extra):
    job_id = job_id or str(uuid.uuid4())
    return {"job_id": job_id, "task": "t", "status": "QUEUED", "tick": 0, **extra}


class OwnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "jobs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_owner_acquires_and_records_its_pid(self):
        owner = DirectoryOwner(self.dir).acquire()
        try:
            self.assertIn(f"pid={os.getpid()}", read_owner_note(self.dir))
        finally:
            owner.release()

    def test_second_owner_is_rejected_while_the_first_holds_the_lock(self):
        first = DirectoryOwner(self.dir).acquire()
        try:
            with self.assertRaises(OwnerLockError) as caught:
                DirectoryOwner(self.dir).acquire()
            self.assertIn("already owns", str(caught.exception))
        finally:
            first.release()

    def test_active_ownership_cannot_be_stolen(self):
        first = DirectoryOwner(self.dir).acquire()
        try:
            for _ in range(3):
                with self.assertRaises(OwnerLockError):
                    DirectoryOwner(self.dir).acquire()
        finally:
            first.release()

    def test_normal_release_frees_the_directory(self):
        DirectoryOwner(self.dir).acquire().release()
        second = DirectoryOwner(self.dir).acquire()
        second.release()

    def test_leftover_lock_file_without_a_holder_is_recovered(self):
        self.dir.mkdir(parents=True)
        (self.dir / OWNER_LOCK_NAME).write_text("pid=999999 started=long-ago\n", encoding="utf-8")

        owner = DirectoryOwner(self.dir).acquire()
        try:
            self.assertIn(f"pid={os.getpid()}", read_owner_note(self.dir))
        finally:
            owner.release()

    def test_owner_that_crashed_without_releasing_does_not_block_a_new_owner(self):
        code = (
            "import os\n"
            "from tools.pipeline.records import DirectoryOwner\n"
            f"DirectoryOwner({str(self.dir)!r}).acquire()\n"
            "os._exit(0)  # simulate a crash: no release, no cleanup\n"
        )
        subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], check=True)

        owner = DirectoryOwner(self.dir).acquire()
        owner.release()


class RecordStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecordStore(Path(self._tmp.name) / "jobs")

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read_round_trips(self):
        record = _record()
        self.store.write_new(record)

        self.assertEqual(self.store.read(record["job_id"])["task"], "t")

    def test_update_changes_only_what_it_returns(self):
        record = _record()
        self.store.write_new(record)
        self.store.update(record["job_id"], lambda r: {"status": "RUNNING"})

        stored = self.store.read(record["job_id"])
        self.assertEqual(stored["status"], "RUNNING")
        self.assertEqual(stored["task"], "t")

    def test_failed_mutation_writes_nothing(self):
        record = _record()
        self.store.write_new(record)

        def refuse(_):
            raise RuntimeError("no")

        with self.assertRaises(RuntimeError):
            self.store.update(record["job_id"], refuse)
        self.assertEqual(self.store.read(record["job_id"])["status"], "QUEUED")

    def test_concurrent_updates_do_not_lose_changes(self):
        record = _record()
        self.store.write_new(record)
        threads = [
            threading.Thread(target=self.store.update, args=(record["job_id"], lambda r: {"tick": r["tick"] + 1}))
            for _ in range(40)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(self.store.read(record["job_id"])["tick"], 40)

    def test_partial_temp_file_from_a_crashed_write_is_ignored_and_removed(self):
        record = _record()
        self.store.write_new(record)
        partial = self.store.directory / f"{record['job_id']}.json.abc123.tmp"
        partial.write_text('{"job_id": "half', encoding="utf-8")

        self.assertEqual(self.store.read(record["job_id"])["job_id"], record["job_id"])
        self.assertEqual(self.store.remove_temp_files(), 1)
        self.assertFalse(partial.exists())

    def test_temp_cleanup_leaves_unrelated_files_alone(self):
        self.store.directory.mkdir(parents=True)
        unrelated = self.store.directory / "notes.tmp"
        unrelated.write_text("keep me", encoding="utf-8")

        self.store.remove_temp_files()

        self.assertTrue(unrelated.exists())

    def test_malformed_json_is_reported_as_corrupt_and_kept(self):
        job_id = str(uuid.uuid4())
        self.store.directory.mkdir(parents=True)
        path = self.store.directory / f"{job_id}.json"
        path.write_text("{not json", encoding="utf-8")

        with self.assertRaises(RecordCorrupt):
            self.store.read(job_id)
        self.assertTrue(path.exists())

    def test_record_that_names_another_job_is_corrupt(self):
        job_id = str(uuid.uuid4())
        self.store.directory.mkdir(parents=True)
        (self.store.directory / f"{job_id}.json").write_text(json.dumps({"job_id": str(uuid.uuid4())}), encoding="utf-8")

        with self.assertRaises(RecordCorrupt):
            self.store.read(job_id)

    def test_ids_ignore_names_that_are_not_job_ids(self):
        good = _record()
        self.store.write_new(good)
        (self.store.directory / "notes.json").write_text("{}", encoding="utf-8")

        self.assertEqual(self.store.ids(), [good["job_id"]])

    def test_invalid_job_id_never_builds_a_path(self):
        with self.assertRaises(ValueError):
            self.store.read("../../outside")


if __name__ == "__main__":
    unittest.main()
