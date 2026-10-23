# Structured JSON Lines audit logger for Synora Agent Bridge
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SENSITIVE_KEYS = {'secret', 'token', 'signature', 'key', 'password', 'authorization', 'bearer'}

# Credential formats redacted from free-text values, wherever they appear. Key-name matching alone
# misses secrets pasted into text fields.
SECRET_VALUE_PATTERNS = [
    re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'),
    re.compile(r'gh[pousr]_[A-Za-z0-9]{36}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{50,}'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)', re.DOTALL),
]


def redact_secret_values(text: str) -> str:
    for pattern in SECRET_VALUE_PATTERNS:
        text = pattern.sub('[REDACTED_SECRET]', text)
    return text

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def scrub_sensitive(data: Any, depth: int = 0) -> Any:
    if depth > 5:
        return '<depth_limit>'
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if any(s in str(k).lower() for s in SENSITIVE_KEYS):
                cleaned[k] = '[REDACTED]'
            else:
                cleaned[k] = scrub_sensitive(v, depth + 1)
        return cleaned
    if isinstance(data, list):
        return [scrub_sensitive(item, depth + 1) for item in data[:50]]
    if isinstance(data, str):
        data = redact_secret_values(data)
        if len(data) > 1000:
            return data[:1000] + '... [TRUNCATED]'
    return data

class AuditLogger:
    def __init__(self, log_path: Optional[Path | str] = None):
        self.log_path = Path(log_path) if log_path else None
        self._lock = threading.Lock()
        self._memory_events = []
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, actor_id: str, details: Optional[Dict[str, Any]] = None) -> dict:
        entry = {
            'timestamp': _now_iso(),
            'event_type': event_type,
            'actor_id': actor_id,
            'details': scrub_sensitive(details or {}),
        }
        with self._lock:
            self._memory_events.append(entry)
            if self.log_path:
                try:
                    with open(self.log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(entry) + chr(10))
                except Exception:
                    pass
        return entry

    def events(self) -> list:
        with self._lock:
            return list(self._memory_events)

AuditLogger.log = AuditLogger.record
