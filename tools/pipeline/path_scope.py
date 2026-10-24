"""Path authorization shared by the Gateway's repair gate, the registry and the bridge.

Two rules apply to every role, including Johan's:

1. Control plane: the Agent Bridge code and deployment, CI workflows, code-ownership files, and secret-looking names
   can never be written by an AI job. A developer cannot widen this with a registry entry.
2. Allow-list: a path is allowed only if a developer's module entry covers it. A directory entry ends with "/" and
   matches by prefix. A file entry (for example "README.md") matches exactly. "*" means every path that is not
   in the control plane.

Anything unparseable, traversing ("..") or absolute-with-drive fails closed.
"""

import re
from typing import Optional, Sequence

CONTROL_PLANE_PREFIXES = (
    "tools/pipeline/",        # Agent Bridge, Gateway, Worker, deployment and their docs
    ".github/workflows/",     # CI and automation
)
CONTROL_PLANE_FILES = (
    ".github/codeowners",     # code-ownership rules (compared case-insensitively)
)
SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
SENSITIVE_BASENAMES = (".env",)
SENSITIVE_DIRECTORIES = ("secrets/", "keys/")
_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_path(path: str) -> Optional[str]:
    """Repository-relative path with forward slashes, or None when it cannot be trusted."""
    if not isinstance(path, str) or not path.strip():
        return None
    value = path.strip().replace("\\", "/")
    if _DRIVE.match(value):
        return None
    value = value.lstrip("/")
    if not value or ".." in value.split("/"):
        return None
    return value


def is_control_plane(path: str) -> bool:
    """True for control-plane paths, and for anything that cannot be normalized (fail closed)."""
    value = normalize_path(path)
    if value is None:
        return True
    folded = value.casefold()
    if any(folded.startswith(prefix) for prefix in CONTROL_PLANE_PREFIXES):
        return True
    if folded in CONTROL_PLANE_FILES:
        return True
    parts = folded.split("/")
    if parts[-1] in SENSITIVE_BASENAMES or parts[-1].endswith(SENSITIVE_SUFFIXES):
        return True
    directories = parts[:-1]
    return any(name.rstrip("/") in directories for name in SENSITIVE_DIRECTORIES)


def _entry_matches(path: str, entry: str) -> bool:
    if entry == "*":
        return True
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry


def allowed_path(path: str, modules: Optional[Sequence[str]]) -> bool:
    """True only when the path is outside the control plane and covered by one of the developer's module entries."""
    if not modules:
        return False  # no authorized scope: fail closed
    if is_control_plane(path):
        return False
    value = normalize_path(path)
    return any(_entry_matches(value, entry) for entry in modules)


def is_file_entry(entry: str) -> bool:
    """A module entry that names a file, such as README.md. Directory entries end with '/'."""
    last = entry.rstrip("/").split("/")[-1]
    return entry != "*" and not entry.endswith("/") and "." in last
