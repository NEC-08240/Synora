# Synora Agent Gateway coordination engine
import asyncio
import base64
import contextlib
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .metadata import MAX_TASK_CHARS
from .audit import AuditLogger
from .auth import (
    AuthenticationError,
    ChallengeStore,
    create_session_token,
    verify_developer_signature,
    verify_session_token,
)
from .authorization import AuthorizationError, AuthorizationPolicy
from .contribution_gate import ContributionGate, ContributionGateError
from .queue import JobQueue, RateLimitExceeded
from .result_envelope import (
    InvalidResultSignature,
    ResultEnvelope,
    ResultEnvelopeError,
    ResultExpired,
    ResultMismatchError,
    ResultReplayDetected,
)
from .team_registry import DeveloperEntry, TeamRegistry
from .worker_registry import WorkerNotFound, WorkerRegistry



logger = logging.getLogger(__name__)


class RecoveryScheduler:
    """Lightweight asyncio background scheduler for periodic stale-worker and job recovery."""

    def __init__(
        self,
        queue: JobQueue,
        interval_seconds: float = 30.0,
        worker_stale_timeout: float = 60.0,
        job_ttl_seconds: float = 86400.0,
        audit: Optional[AuditLogger] = None,
    ):
        self.queue = queue
        self.interval = float(interval_seconds)
        self.worker_stale_timeout = float(worker_stale_timeout)
        self.job_ttl = float(job_ttl_seconds)
        self.audit = audit
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def run_once(self) -> tuple:
        loop = asyncio.get_running_loop()
        reaped = await loop.run_in_executor(None, self.queue.reap_stale_workers, self.worker_stale_timeout)
        expired = await loop.run_in_executor(None, self.queue.expire_stale_jobs, self.job_ttl)
        if self.audit:
            if reaped:
                self.audit.record('WORKERS_REAPED', 'scheduler', {'reaped_workers': reaped})
            if expired:
                self.audit.record('JOBS_EXPIRED', 'scheduler', {'expired_jobs': expired})
        return reaped, expired

    async def _loop(self):
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                if not self._running:
                    break
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error(f'Error in recovery loop: {err}')

    def start(self):
        if self._running or (self._task is not None and not self._task.done()):
            return  # Prevent duplicate scheduler tasks
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


class Gateway:
    def __init__(
        self,
        registry: TeamRegistry,
        queue: Optional[JobQueue] = None,
        audit: Optional[AuditLogger] = None,
        signing_secret: Optional[bytes] = None,
        worker_registry: Optional[WorkerRegistry] = None,
        max_jobs_per_developer: int = 1,
        max_task_size: int = MAX_TASK_CHARS,
        max_diff_size: int = 524288,
        max_result_age_seconds: float = 300.0,
        worker_online_window_seconds: float = 30.0,
    ):
        self.registry = registry
        self.queue = queue or JobQueue(':memory:')
        self.audit = audit or AuditLogger()
        self.signing_secret = signing_secret or secrets.token_bytes(32)
        self.challenges = ChallengeStore(default_ttl_seconds=300)
        self.worker_challenges = ChallengeStore(default_ttl_seconds=60)
        self.worker_registry = worker_registry or WorkerRegistry()
        self.recovery_scheduler = RecoveryScheduler(queue=self.queue, audit=self.audit)
        self.max_jobs_per_developer = max_jobs_per_developer
        self.max_task_size = max_task_size
        self.max_diff_size = max_diff_size
        self.max_result_age_seconds = max_result_age_seconds
        self.worker_online_window_seconds = worker_online_window_seconds
        self._worker_tokens = {}

    def request_challenge(self, developer_id: str) -> dict:
        dev = self.registry.get(developer_id)
        if not dev.is_active():
            self.audit.record('AUTH_CHALLENGE_REJECTED', developer_id, {'reason': 'suspended'})
            raise AuthenticationError(f'Developer {developer_id!r} is suspended.')
        challenge = self.challenges.create(developer_id)
        self.audit.record('AUTH_CHALLENGE_ISSUED', developer_id, {'nonce': challenge['nonce']})
        return challenge

    def authenticate(self, developer_id: str, nonce: str, signature_b64: str) -> str:
        dev = self.registry.get(developer_id)
        message = self.challenges.consume(developer_id, nonce)
        try:
            verify_developer_signature(dev, message, signature_b64)
        except Exception as err:
            self.audit.record('AUTH_FAILED', developer_id, {'error': str(err)})
            raise
        token = create_session_token(dev, self.signing_secret, ttl_seconds=3600)
        self.audit.record('AUTH_SUCCESS', developer_id, {'role': dev.role})
        return token

    def verify_caller(self, token_str: str) -> DeveloperEntry:
        return verify_session_token(token_str, self.signing_secret, self.registry)

    def submit_job(self, token_str: str, job_payload: dict) -> dict:
        caller = self.verify_caller(token_str)

        # Enforce authenticated identity over any submitted developer_id
        submitted_dev_id = job_payload.get('developer_id')
        if submitted_dev_id and submitted_dev_id != caller.developer_id:
            self.audit.record(
                'SUBMISSION_REJECTED',
                caller.developer_id,
                {'reason': 'identity_mismatch', 'submitted': submitted_dev_id},
            )
            raise AuthorizationError(
                f'Submitted developer_id {submitted_dev_id!r} does not match authenticated identity {caller.developer_id!r}.'
            )

        is_repair = bool(job_payload.get('is_repair'))
        task = job_payload.get('task')
        if not isinstance(task, str):
            raise ValueError('task must be a string.')
        task_type = job_payload.get('task_type', 'docs')
        if not isinstance(task_type, str):
            raise ValueError('task_type must be a string.')
        branch = job_payload.get('branch')
        if not isinstance(branch, str):
            raise ValueError('branch must be a string.')
        base_commit = job_payload.get('base_commit')
        if not isinstance(base_commit, str):
            raise ValueError('base_commit must be a string.')
        diff = job_payload.get('diff', '')
        if not isinstance(diff, str):
            raise ValueError('diff must be a string.')
        local_evidence = job_payload.get('local_evidence')

        # Size validations
        if len(task) > self.max_task_size:
            raise ValueError(
                f'Task size ({len(task)} chars) exceeds maximum allowed ({self.max_task_size}).'
            )
        if len(diff) > self.max_diff_size:
            raise ValueError(
                f'Diff size ({len(diff)} chars) exceeds maximum allowed ({self.max_diff_size}).'
            )

        try:
            gate_res = ContributionGate.validate(
                developer=caller,
                task=task,
                task_type=task_type,
                branch=branch,
                base_commit=base_commit,
                is_repair=is_repair,
                developer_diff=diff,
                local_evidence=local_evidence,
            )
            self.audit.record('GATE_PASS', caller.developer_id, gate_res)
        except ContributionGateError as err:
            self.audit.record('GATE_REJECT', caller.developer_id, {'error': str(err)})
            raise

        AuthorizationPolicy.check_submit_task(caller, branch, task_type, gate_res.get('changed_files'))

        job_id = str(uuid.uuid4())
        enqueue_record = {
            'job_id': job_id,
            'developer_id': caller.developer_id,
            'task': task,
            'task_type': task_type,
            'branch': branch,
            'base_commit': base_commit,
            'diff': diff,
            'is_repair': is_repair,
        }
        self.queue.enqueue(enqueue_record, max_per_developer=self.max_jobs_per_developer)
        self.audit.record('JOB_ENQUEUED', caller.developer_id, {'job_id': job_id, 'branch': branch})
        return {'success': True, 'job_id': job_id, 'status': 'QUEUED'}

    def get_status(self, token_str: str, job_id: str) -> dict:
        caller = self.verify_caller(token_str)
        job = self.queue.get_job(job_id)
        if not job:
            raise KeyError(f'Job {job_id} not found.')
        AuthorizationPolicy.check_job_access(caller, job, action='status')
        return {
            'job_id': job['job_id'],
            'developer_id': job['developer_id'],
            'status': job['status'],
            'task_type': job['task_type'],
            'branch': job['branch'],
            'created_at': job['created_at'],
            'updated_at': job['updated_at'],
            'assigned_at': job.get('assigned_at'),
            'finished_at': job.get('finished_at'),
            'error': job.get('error') or '',
        }

    def get_result(self, token_str: str, job_id: str) -> dict:
        caller = self.verify_caller(token_str)
        job = self.queue.get_job(job_id)
        if not job:
            raise KeyError(f'Job {job_id} not found.')
        AuthorizationPolicy.check_job_access(caller, job, action='result')
        res = dict(job)
        if isinstance(job.get('result'), dict):
            res.update(job['result'])
        return res

    def cancel_job(self, token_str: str, job_id: str) -> dict:
        caller = self.verify_caller(token_str)
        success = self.queue.cancel_job(job_id, caller.developer_id, is_owner=caller.is_owner())
        if not success:
            raise RuntimeError(
                f'Could not cancel job {job_id}: job not found, not owned, or already finished.'
            )
        self.audit.record('JOB_CANCELLED', caller.developer_id, {'job_id': job_id})
        return {'success': True, 'job_id': job_id, 'status': 'CANCELLED'}

    def request_worker_challenge(self, worker_id: str) -> dict:
        worker_entry = self.worker_registry.get(worker_id)
        if not worker_entry.is_active():
            self.audit.record('WORKER_CHALLENGE_REJECTED', worker_id, {'reason': 'suspended'})
            raise AuthenticationError(f'Worker {worker_id!r} is suspended.')
        challenge = self.worker_challenges.create(worker_id)
        self.audit.record('WORKER_CHALLENGE_ISSUED', worker_id, {'nonce': challenge['nonce']})
        return {
            'worker_id': worker_id,
            'nonce': challenge['nonce'],
            'message': challenge['message'],
            'expires_at': challenge['expires_at'],
        }

    def authenticate_worker(self, worker_id: str, nonce: str, signature_b64: str) -> None:
        worker_entry = self.worker_registry.get(worker_id)
        if not worker_entry.is_active():
            self.audit.record('WORKER_AUTH_REJECTED', worker_id, {'reason': 'suspended'})
            raise AuthenticationError(f'Worker {worker_id!r} is suspended.')
        message = self.worker_challenges.consume(worker_id, nonce)
        try:
            raw_sig = base64.b64decode(signature_b64.strip(), validate=True)
            pub = worker_entry.get_public_key()
            pub.verify(raw_sig, message.encode('utf-8'))
        except Exception as err:
            self.audit.record('WORKER_AUTH_FAILED', worker_id, {'error': str(err)})
            raise AuthenticationError(f'Worker signature verification failed: {err}') from None
        self.audit.record('WORKER_AUTH_SUCCESS', worker_id, {})

    def register_worker(self, worker_id: str, worker_token: str, capabilities: dict) -> dict:
        self.queue.heartbeat_worker(worker_id, capabilities)
        self._worker_tokens[worker_id] = worker_token
        self.audit.record('WORKER_ONLINE', worker_id, capabilities)
        return {'success': True, 'worker_id': worker_id, 'status': 'REGISTERED'}

    def worker_heartbeat(self, worker_id: str) -> dict:
        self.queue.heartbeat_worker(worker_id)
        return {'success': True, 'status': 'PONG'}

    def worker_poll_job(self, worker_id: str) -> Optional[dict]:
        self.queue.heartbeat_worker(worker_id)
        job = self.queue.claim_next(worker_id)
        if job:
            self.audit.record(
                'JOB_CLAIMED', worker_id, {'job_id': job['job_id'], 'developer_id': job['developer_id']}
            )
        return job

    def worker_submit_result(self, worker_id: str, job_id: str, result_dict: dict) -> dict:
        self.queue.complete_job(job_id, worker_id, result_dict)
        self.audit.record('JOB_COMPLETED', worker_id, {'job_id': job_id, 'status': result_dict.get('status')})
        return {'success': True}

    def worker_submit_failure(self, worker_id: str, job_id: str, error_msg: str) -> dict:
        self.queue.fail_job(job_id, worker_id, error_msg)
        self.audit.record('JOB_FAILED', worker_id, {'job_id': job_id, 'error': error_msg})
        return {'success': True}

    def worker_submit_signed_result(self, envelope: dict) -> dict:
        if not isinstance(envelope, dict):
            raise ResultEnvelopeError('Result envelope must be a dictionary.')

        worker_id = envelope.get('worker_id')
        job_id = envelope.get('job_id')
        developer_id = envelope.get('developer_id')
        nonce = envelope.get('nonce')

        if not worker_id or not job_id or not nonce or not developer_id:
            raise ResultEnvelopeError('Missing required fields in result envelope.')

        worker_entry = self.worker_registry.get(worker_id)
        if not worker_entry.is_active():
            self.audit.record('RESULT_REJECTED', worker_id, {'reason': 'worker_suspended', 'job_id': job_id})
            raise AuthenticationError(f'Worker {worker_id!r} is {worker_entry.status}.')

        # Replay protection
        if not self.queue.record_nonce_if_new(nonce, worker_id):
            self.audit.record(
                'RESULT_REJECTED', worker_id, {'reason': 'replay_detected', 'nonce': nonce, 'job_id': job_id}
            )
            raise ResultReplayDetected(f'Nonce {nonce!r} has already been used.')

        # Cross-reference with job in queue
        job = self.queue.get_job(job_id)
        if not job:
            raise KeyError(f'Job {job_id!r} not found.')

        if job.get('worker_id') and job['worker_id'] != worker_id:
            raise ResultMismatchError(
                f"Job {job_id!r} was claimed by {job['worker_id']!r}, not {worker_id!r}."
            )

        if job['developer_id'] != developer_id:
            raise ResultMismatchError(
                f"Job developer {job['developer_id']!r} does not match envelope developer {developer_id!r}."
            )

        # Cryptographic verification
        ResultEnvelope.verify(
            envelope=envelope,
            public_key=worker_entry.get_public_key(),
            expected_job_id=job_id,
            expected_developer_id=job['developer_id'],
            expected_worker_id=worker_id,
            max_age_seconds=self.max_result_age_seconds,
        )

        status = envelope['status']
        if status in ('SUCCEEDED', 'COMPLETED'):
            self.queue.complete_job(job_id, worker_id, envelope['result'])
        else:
            error_text = envelope['result'].get('error', f'Status: {status}')
            self.queue.fail_job(job_id, worker_id, error_text)

        self.audit.record('JOB_RESULT_VERIFIED', worker_id, {'job_id': job_id, 'status': status})
        return {'success': True, 'job_id': job_id, 'status': status}

    def _is_online(self, beat: Optional[dict]) -> bool:
        """A worker is online only if the Gateway heard from it recently. 'status' is enrolment, not liveness."""
        if not beat or beat.get('status') != 'ONLINE':
            return False
        try:
            seen = datetime.fromisoformat(beat['last_heartbeat'])
        except (KeyError, TypeError, ValueError):
            return False
        return (datetime.now(timezone.utc) - seen).total_seconds() < self.worker_online_window_seconds

    def get_worker_status(self) -> dict:
        workers = self.worker_registry.list_workers()
        beats = self.queue.worker_heartbeats()
        return {
            'workers': [
                {
                    'worker_id': w.worker_id,
                    'status': w.status,
                    'online': self._is_online(beats.get(w.worker_id)),
                    'last_heartbeat': (beats.get(w.worker_id) or {}).get('last_heartbeat'),
                    'capabilities': w.capabilities,
                    'created_at': w.created_at,
                }
                for w in workers
            ]
        }
