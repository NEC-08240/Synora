# Worker identity registry for Synora Agent Bridge
import base64
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

WORKER_STATUSES = ('active', 'suspended')
WORKER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{2,64}$')


class WorkerRegistryError(ValueError):
    pass


class WorkerNotFound(KeyError, WorkerRegistryError):
    pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _validate_worker_public_key(pub_b64: str) -> str:
    if not isinstance(pub_b64, str) or not pub_b64.strip():
        raise WorkerRegistryError('Public key must be a non-empty string.')
    try:
        raw = base64.b64decode(pub_b64.strip(), validate=True)
    except Exception as err:
        raise WorkerRegistryError(f'Public key is not valid base64: {err}') from None
    if len(raw) != 32:
        raise WorkerRegistryError(f'Ed25519 public key must be exactly 32 bytes, got {len(raw)}.')
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(raw)
    except Exception as err:
        raise WorkerRegistryError(f'Invalid Ed25519 public key: {err}') from None
    return pub_b64.strip()


@dataclass
class WorkerEntry:
    worker_id: str
    public_key_b64: str
    status: str = 'active'
    capabilities: Dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)

    def is_active(self) -> bool:
        return self.status == 'active'

    def get_public_key(self) -> ed25519.Ed25519PublicKey:
        raw = base64.b64decode(self.public_key_b64)
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)


class WorkerRegistry:
    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else None
        self._workers: Dict[str, WorkerEntry] = {}
        if self.storage_path and self.storage_path.exists():
            self._load()

    def enroll(
        self,
        worker_id: str,
        public_key_b64: str,
        status: str = 'active',
        capabilities: Optional[Dict] = None,
    ) -> WorkerEntry:
        if not WORKER_ID_PATTERN.match(worker_id):
            raise WorkerRegistryError(
                f'Invalid worker_id {worker_id!r}. Must match regex {WORKER_ID_PATTERN.pattern}'
            )
        if worker_id in self._workers:
            raise WorkerRegistryError(f'Worker {worker_id!r} is already enrolled.')
        if status not in WORKER_STATUSES:
            raise WorkerRegistryError(f'Invalid status {status!r}. Must be one of {WORKER_STATUSES}.')

        clean_key = _validate_worker_public_key(public_key_b64)
        entry = WorkerEntry(
            worker_id=worker_id,
            public_key_b64=clean_key,
            status=status,
            capabilities=capabilities or {'supported_tasks': ['docs', 'code', 'review']},
        )
        self._workers[worker_id] = entry
        self._save()
        return entry

    def get(self, worker_id: str) -> WorkerEntry:
        if worker_id not in self._workers:
            raise WorkerNotFound(f'Worker {worker_id!r} not found in registry.')
        return self._workers[worker_id]

    def suspend(self, worker_id: str) -> WorkerEntry:
        entry = self.get(worker_id)
        entry.status = 'suspended'
        self._save()
        return entry

    def activate(self, worker_id: str) -> WorkerEntry:
        entry = self.get(worker_id)
        entry.status = 'active'
        self._save()
        return entry

    def list_workers(self) -> List[WorkerEntry]:
        return list(self._workers.values())

    def _save(self):
        if not self.storage_path:
            return
        data = {w_id: asdict(entry) for w_id, entry in self._workers.items()}
        tmp_path = self.storage_path.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.storage_path)

    def _load(self):
        with open(self.storage_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for w_id, entry_dict in data.items():
            self._workers[w_id] = WorkerEntry(**entry_dict)
