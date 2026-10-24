# Team identity registry for Synora Agent Bridge
import base64
import fnmatch
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .path_scope import allowed_path, is_file_entry

ROLES = ('project_owner', 'developer', 'auditor')
STATUSES = ('active', 'suspended')

DEVELOPER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}\Z')
GITHUB_USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$')

class RegistryError(ValueError):
    pass

class DeveloperNotFound(KeyError, RegistryError):
    pass

def _validate_public_key(pub_b64: str) -> str:
    if not isinstance(pub_b64, str) or not pub_b64.strip():
        raise RegistryError('Public key must be a non-empty base64-encoded string.')
    try:
        raw = base64.b64decode(pub_b64.strip(), validate=True)
    except Exception as err:
        raise RegistryError(f'Public key is not valid base64: {err}') from None
    if len(raw) != 32:
        raise RegistryError(f'Ed25519 public key must decode to exactly 32 bytes (got {len(raw)}).')
    return pub_b64.strip()

def _validate_module_scope(modules: Sequence[str]) -> Tuple[str, ...]:
    cleaned = []
    for mod in modules:
        if not isinstance(mod, str) or not mod.strip():
            raise RegistryError('Module scopes must be non-empty strings.')
        m = mod.strip().replace(chr(92), '/')
        if '..' in m.split('/'):
            raise RegistryError(f'Path traversal forbidden in assigned module scope: {mod!r}')
        if m.startswith('/'):
            raise RegistryError(f'Module scope must be relative to repository root: {mod!r}')
        if m != '*' and not m.endswith('/') and not is_file_entry(m):
            m = m + '/'  # a directory entry; file entries such as README.md stay exact
        cleaned.append(m)
    return tuple(cleaned)

def _validate_branch_patterns(branches: Sequence[str]) -> Tuple[str, ...]:
    cleaned = []
    for b in branches:
        if not isinstance(b, str) or not b.strip():
            raise RegistryError('Branch patterns must be non-empty strings.')
        cleaned.append(b.strip())
    return tuple(cleaned)

@dataclass(frozen=True)
class DeveloperEntry:
    developer_id: str
    developer_name: str
    github_username: str
    role: str
    status: str
    public_key_ed25519: str = ""
    assigned_modules: Tuple[str, ...] = ('*',)
    allowed_branches: Tuple[str, ...] = ('*',)
    rate_limits: Dict[str, int] = field(default_factory=lambda: {'max_concurrent_jobs': 1, 'max_daily_repairs': 20})
    public_key_b64: Optional[str] = None

    def __post_init__(self):
        if not self.public_key_ed25519 and self.public_key_b64:
            object.__setattr__(self, 'public_key_ed25519', self.public_key_b64)
        elif self.public_key_ed25519 and not self.public_key_b64:
            object.__setattr__(self, 'public_key_b64', self.public_key_ed25519)
        if not DEVELOPER_ID_PATTERN.match(self.developer_id):
            raise RegistryError(f'Invalid developer_id {self.developer_id!r}: must be 2-64 alphanumeric, dash, or underscore.')
        if not self.developer_name.strip():
            raise RegistryError('developer_name must be non-empty.')
        if not GITHUB_USERNAME_PATTERN.match(self.github_username):
            raise RegistryError(f'Invalid github_username: {self.github_username!r}')
        if self.role not in ROLES:
            raise RegistryError(f'Invalid role {self.role!r}. Allowed: {ROLES}')
        if self.status not in STATUSES:
            raise RegistryError(f'Invalid status {self.status!r}. Allowed: {STATUSES}')
        object.__setattr__(self, 'public_key_ed25519', _validate_public_key(self.public_key_ed25519))
        object.__setattr__(self, 'assigned_modules', _validate_module_scope(self.assigned_modules))
        object.__setattr__(self, 'allowed_branches', _validate_branch_patterns(self.allowed_branches))

    def is_active(self) -> bool:
        return self.status == 'active'

    def is_owner(self) -> bool:
        return self.role == 'project_owner'

    def can_touch_file(self, file_path: str) -> bool:
        return allowed_path(file_path, self.assigned_modules)

    def can_touch_branch(self, branch_name: str) -> bool:
        if '*' in self.allowed_branches:
            return True
        return any(fnmatch.fnmatch(branch_name, pat) for pat in self.allowed_branches)

class TeamRegistry:
    def __init__(self, entries: Optional[Sequence[DeveloperEntry]] = None):
        self._entries: Dict[str, DeveloperEntry] = {}
        if entries:
            for entry in entries:
                self.register(entry)

    def register(self, entry: DeveloperEntry) -> None:
        if entry.developer_id in self._entries:
            raise RegistryError(f'Duplicate developer_id: {entry.developer_id!r} is already registered.')
        self._entries[entry.developer_id] = entry

    def update(self, entry: DeveloperEntry) -> None:
        if entry.developer_id not in self._entries:
            raise DeveloperNotFound(f'Developer {entry.developer_id!r} does not exist to update.')
        self._entries[entry.developer_id] = entry

    def suspend(self, developer_id: str) -> DeveloperEntry:
        existing = self.get(developer_id)
        updated = DeveloperEntry(
            developer_id=existing.developer_id,
            developer_name=existing.developer_name,
            github_username=existing.github_username,
            role=existing.role,
            status='suspended',
            public_key_ed25519=existing.public_key_ed25519,
            assigned_modules=existing.assigned_modules,
            allowed_branches=existing.allowed_branches,
            rate_limits=existing.rate_limits,
        )
        self._entries[developer_id] = updated
        return updated

    def activate(self, developer_id: str) -> DeveloperEntry:
        existing = self.get(developer_id)
        updated = DeveloperEntry(
            developer_id=existing.developer_id,
            developer_name=existing.developer_name,
            github_username=existing.github_username,
            role=existing.role,
            status='active',
            public_key_ed25519=existing.public_key_ed25519,
            assigned_modules=existing.assigned_modules,
            allowed_branches=existing.allowed_branches,
            rate_limits=existing.rate_limits,
        )
        self._entries[developer_id] = updated
        return updated

    def get(self, developer_id: str) -> DeveloperEntry:
        if developer_id not in self._entries:
            raise DeveloperNotFound(f'Developer {developer_id!r} not found in team registry.')
        return self._entries[developer_id]

    def get_by_github(self, github_username: str) -> Optional[DeveloperEntry]:
        for entry in self._entries.values():
            if entry.github_username.lower() == github_username.lower():
                return entry
        return None

    def is_active(self, developer_id: str) -> bool:
        entry = self._entries.get(developer_id)
        return bool(entry and entry.is_active())

    def list_all(self) -> List[DeveloperEntry]:
        return list(self._entries.values())

    def list_active(self) -> List[DeveloperEntry]:
        return [e for e in self._entries.values() if e.is_active()]

    def to_dict(self) -> dict:
        return {'developers': [asdict(e) for e in self._entries.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> 'TeamRegistry':
        if not isinstance(data, dict) or 'developers' not in data:
            raise RegistryError('Registry JSON must have a top-level developers array.')
        entries = []
        for raw in data['developers']:
            raw_copy = dict(raw)
            raw_copy['assigned_modules'] = tuple(raw_copy.get('assigned_modules', ('*',)))
            raw_copy['allowed_branches'] = tuple(raw_copy.get('allowed_branches', ('*',)))
            entries.append(DeveloperEntry(**raw_copy))
        return cls(entries)

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(), indent=2)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + '.', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as h:
                h.write(text)
                h.flush()
                os.fsync(h.fileno())
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path | str) -> 'TeamRegistry':
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f'Team registry file not found: {p}')
        data = json.loads(p.read_text(encoding='utf-8'))
        return cls.from_dict(data)
