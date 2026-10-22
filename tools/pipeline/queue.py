# Persistent, stateful SQLite job queue for Synora Agent Gateway
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional


class QueueFullError(ValueError, RuntimeError):
    pass


class RateLimitExceeded(ValueError, RuntimeError):
    pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = (
    'CREATE TABLE IF NOT EXISTS jobs ('
    'job_id TEXT PRIMARY KEY, '
    'developer_id TEXT NOT NULL, '
    'task TEXT NOT NULL, '
    'task_type TEXT NOT NULL, '
    'branch TEXT NOT NULL, '
    'base_commit TEXT NOT NULL, '
    'diff TEXT, '
    'is_repair INTEGER NOT NULL DEFAULT 0, '
    'status TEXT NOT NULL, '
    'worker_id TEXT, '
    'created_at TEXT NOT NULL, '
    'updated_at TEXT NOT NULL, '
    'assigned_at TEXT, '
    'finished_at TEXT, '
    'result_json TEXT, '
    'error TEXT);'
)

WORKERS_SQL = (
    'CREATE TABLE IF NOT EXISTS workers ('
    'worker_id TEXT PRIMARY KEY, '
    'status TEXT NOT NULL, '
    'last_heartbeat TEXT NOT NULL, '
    'capabilities TEXT);'
)

NONCES_SQL = (
    'CREATE TABLE IF NOT EXISTS seen_nonces ('
    'nonce TEXT PRIMARY KEY, '
    'worker_id TEXT NOT NULL, '
    'seen_at TEXT NOT NULL);'
)


class JobQueue:
    def __init__(self, db_path: str = ':memory:', max_depth: int = 100):
        self.db_path = db_path
        self.max_depth = max_depth
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            with self._conn:
                self._conn.execute(SCHEMA_SQL)
                self._conn.execute(WORKERS_SQL)
                self._conn.execute(NONCES_SQL)

    def enqueue(self, job_dict: dict, max_per_developer: Optional[int] = None) -> str:
        job_id = job_dict['job_id']
        developer_id = job_dict['developer_id']
        now = _now_iso()
        with self._lock:
            with self._conn:
                if max_per_developer is not None:
                    cur = self._conn.execute(
                        'SELECT COUNT(*) FROM jobs WHERE developer_id = ? AND status IN (?, ?, ?);',
                        (developer_id, 'QUEUED', 'ASSIGNED', 'RUNNING'),
                    )
                    active_count = cur.fetchone()[0]
                    if active_count >= max_per_developer:
                        raise RateLimitExceeded(
                            f'Developer {developer_id!r} has reached maximum concurrent active jobs ({max_per_developer}).'
                        )

                cur = self._conn.execute('SELECT COUNT(*) FROM jobs WHERE status = ?;', ('QUEUED',))
                count = cur.fetchone()[0]
                if count >= self.max_depth:
                    raise QueueFullError(f'Queue depth limit reached ({self.max_depth} jobs).')

                insert_sql = (
                    'INSERT INTO jobs (job_id, developer_id, task, task_type, branch, base_commit, '
                    'diff, is_repair, status, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);'
                )
                self._conn.execute(
                    insert_sql,
                    (
                        job_id,
                        developer_id,
                        job_dict['task'],
                        job_dict.get('task_type', 'docs'),
                        job_dict.get('branch', ''),
                        job_dict.get('base_commit', ''),
                        job_dict.get('diff', ''),
                        1 if job_dict.get('is_repair') else 0,
                        'QUEUED',
                        now,
                        now,
                    ),
                )
        return job_id

    def claim_next(self, worker_id: str) -> Optional[dict]:
        now = _now_iso()
        with self._lock:
            with self._conn:
                query = (
                    'SELECT j.job_id, j.developer_id, j.task, j.task_type, j.branch, j.base_commit, j.diff, j.is_repair '
                    'FROM jobs j '
                    'LEFT JOIN (SELECT developer_id, COUNT(*) as active_count FROM jobs WHERE status IN (?, ?) GROUP BY developer_id) a '
                    'ON j.developer_id = a.developer_id '
                    'WHERE j.status = ? '
                    'ORDER BY COALESCE(a.active_count, 0) ASC, j.created_at ASC LIMIT 1;'
                )
                cur = self._conn.execute(query, ('ASSIGNED', 'RUNNING', 'QUEUED'))
                row = cur.fetchone()
                if not row:
                    return None

                job_id = row['job_id']
                update_sql = (
                    'UPDATE jobs SET status = ?, worker_id = ?, assigned_at = ?, updated_at = ? '
                    'WHERE job_id = ? AND status = ?;'
                )
                res_cur = self._conn.execute(update_sql, ('ASSIGNED', worker_id, now, now, job_id, 'QUEUED'))
                if res_cur.rowcount == 0:
                    return None
                res = dict(row)
                res['status'] = 'ASSIGNED'
                res['worker_id'] = worker_id
                return res

    def record_nonce_if_new(self, nonce: str, worker_id: str) -> bool:
        now = _now_iso()
        with self._lock:
            with self._conn:
                cur = self._conn.execute('SELECT 1 FROM seen_nonces WHERE nonce = ?;', (nonce,))
                if cur.fetchone() is not None:
                    return False
                self._conn.execute(
                    'INSERT INTO seen_nonces (nonce, worker_id, seen_at) VALUES (?, ?, ?);',
                    (nonce, worker_id, now),
                )
                return True

    def heartbeat_worker(self, worker_id: str, capabilities: Optional[dict] = None) -> None:
        now = _now_iso()
        cap_json = json.dumps(capabilities or {})
        with self._lock:
            with self._conn:
                upsert_sql = (
                    'INSERT INTO workers (worker_id, status, last_heartbeat, capabilities) VALUES (?, ?, ?, ?) '
                    'ON CONFLICT(worker_id) DO UPDATE SET status = excluded.status, last_heartbeat = excluded.last_heartbeat, capabilities = excluded.capabilities;'
                )
                self._conn.execute(upsert_sql, (worker_id, 'ONLINE', now, cap_json))

    def reap_stale_workers(self, timeout_seconds: float = 60.0) -> List[str]:
        now = datetime.now(timezone.utc)
        reaped_workers = []
        with self._lock:
            with self._conn:
                cur = self._conn.execute('SELECT worker_id, last_heartbeat FROM workers WHERE status != ?;', ('OFFLINE',))
                for row in cur.fetchall():
                    w_id = row['worker_id']
                    try:
                        hb = datetime.fromisoformat(row['last_heartbeat'])
                        if (now - hb).total_seconds() > timeout_seconds:
                            reaped_workers.append(w_id)
                    except Exception:
                        reaped_workers.append(w_id)

                for w_id in reaped_workers:
                    self._conn.execute('UPDATE workers SET status = ? WHERE worker_id = ?;', ('OFFLINE', w_id))
                    requeue_sql = 'UPDATE jobs SET status = ?, worker_id = NULL, assigned_at = NULL, updated_at = ? WHERE worker_id = ? AND status IN (?, ?);'
                    self._conn.execute(requeue_sql, ('QUEUED', _now_iso(), w_id, 'ASSIGNED', 'RUNNING'))

        return reaped_workers

    def expire_stale_jobs(self, ttl_seconds: float = 86400.0) -> List[str]:
        now_dt = datetime.now(timezone.utc)
        expired_ids = []
        with self._lock:
            with self._conn:
                cur = self._conn.execute('SELECT job_id, created_at FROM jobs WHERE status IN (?, ?, ?);', ('QUEUED', 'ASSIGNED', 'RUNNING'))
                for row in cur.fetchall():
                    try:
                        ct = datetime.fromisoformat(row['created_at'])
                        if (now_dt - ct).total_seconds() > ttl_seconds:
                            expired_ids.append(row['job_id'])
                    except Exception:
                        pass
                for j_id in expired_ids:
                    self._conn.execute(
                        'UPDATE jobs SET status = ?, error = ?, finished_at = ?, updated_at = ? WHERE job_id = ?;',
                        ('EXPIRED', f'Job exceeded TTL ({ttl_seconds}s)', _now_iso(), _now_iso(), j_id),
                    )
        return expired_ids

    def update_progress(self, job_id: str, worker_id: str, status: str, error: str = '') -> None:
        now = _now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    'UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE job_id = ? AND worker_id = ?;',
                    (status, error, now, job_id, worker_id),
                )

    def complete_job(self, job_id: str, worker_id: str, result_dict: dict) -> None:
        now = _now_iso()
        res_json = json.dumps(result_dict)
        final_status = result_dict.get('status', 'SUCCEEDED')
        with self._lock:
            with self._conn:
                self._conn.execute(
                    'UPDATE jobs SET status = ?, result_json = ?, finished_at = ?, updated_at = ? WHERE job_id = ? AND worker_id = ?;',
                    (final_status, res_json, now, now, job_id, worker_id),
                )

    def fail_job(self, job_id: str, worker_id: str, error: str) -> None:
        now = _now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    'UPDATE jobs SET status = ?, error = ?, finished_at = ?, updated_at = ? WHERE job_id = ? AND worker_id = ?;',
                    ('FAILED', error, now, now, job_id, worker_id),
                )

    def cancel_job(self, job_id: str, developer_id: str, is_owner: bool = False) -> bool:
        now = _now_iso()
        with self._lock:
            with self._conn:
                cur = self._conn.execute('SELECT developer_id, status FROM jobs WHERE job_id = ?;', (job_id,))
                row = cur.fetchone()
                if not row:
                    return False
                if not is_owner and row['developer_id'] != developer_id:
                    return False
                if row['status'] in ('SUCCEEDED', 'FAILED', 'ESCALATED', 'CANCELLED', 'EXPIRED'):
                    return False

                self._conn.execute('UPDATE jobs SET status = ?, finished_at = ?, updated_at = ? WHERE job_id = ?;', ('CANCELLED', now, now, job_id))
                return True

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute('SELECT * FROM jobs WHERE job_id = ?;', (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get('result_json'):
                try:
                    d['result'] = json.loads(d['result_json'])
                except Exception:
                    d['result'] = None
            return d

    def list_jobs(self, developer_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> List[dict]:
        query = 'SELECT * FROM jobs WHERE 1=1'
        params = []
        if developer_id:
            query += ' AND developer_id = ?'
            params.append(developer_id)
        if status:
            query += ' AND status = ?'
            params.append(status)
        query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(query, tuple(params))
            results = []
            for row in cur.fetchall():
                d = dict(row)
                if d.get('result_json'):
                    try:
                        d['result'] = json.loads(d['result_json'])
                    except Exception:
                        d['result'] = None
                results.append(d)
            return results

    def close(self):
        with self._lock:
            self._conn.close()
