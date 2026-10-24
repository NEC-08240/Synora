"""Routine-or-escalate policy for pull requests. It fails closed.

A pull request is ROUTINE only when every changed path is under an allowlisted routine prefix, no path looks sensitive,
no added line looks like a credential, no file is a symlink, submodule or executable, and the change is small.
Anything else is ESCALATE, with the reasons, and Johan decides. The input is git's own diff, with renames split into
both sides, so a file moved out of a sensitive folder is still seen.

Run: python -m unittest tools.pipeline.test_merge_policy -v
CLI: python -m tools.pipeline.merge_policy --base origin/main --head HEAD
"""

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from typing import List, Sequence

ROUTINE = "ROUTINE"
ESCALATE = "ESCALATE"

# Only these prefixes can be routine. Everything else escalates, so a new folder is Johan's by default.
ROUTINE_PREFIXES = ("frontend/", "prototypes/", "docs/ui-design/")
MAX_FILES = 40

# Path components (split on / . - _) that mark security or infrastructure work, wherever they appear.
SENSITIVE_TOKENS = frozenset({
    "auth", "login", "logout", "session", "sessions", "credential", "credentials", "secret", "secrets", "token",
    "tokens", "password", "key", "keys", "admin", "migration", "migrations", "deploy", "infra", "production",
    "workflow", "workflows", "codeowners", "ruleset", "lead", "gateway", "worker", "bridge", "pipeline", "tools",
    "database", "backend", "architecture", "operations", "github", "env",
})
SENSITIVE_SUFFIXES = (
    ".key", ".pem", ".p12", ".pfx", ".crt", ".cer", ".db", ".sqlite", ".sqlite3", ".env",
    ".sh", ".ps1", ".bat", ".cmd", ".exe", ".dll", ".so",
)
DEPENDENCY_FILES = frozenset({
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "requirements.txt", "pyproject.toml",
    "setup.py", "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "dockerfile", "docker-compose.yml",
    "gemfile", "gemfile.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "composer.json", "composer.lock",
})
SYMLINK_MODE = "120000"
SUBMODULE_MODE = "160000"
EXECUTABLE_MODES = frozenset({"100755"})

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\b\s*[:=]"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
)


@dataclass(frozen=True)
class FileChange:
    path: str
    old_mode: str
    new_mode: str
    status: str


@dataclass(frozen=True)
class Decision:
    verdict: str
    reasons: List[str]


def parse_raw(output: str) -> List[FileChange]:
    """Parse `git diff --raw -z --no-renames` output: ':old new oldsha newsha status\\0path\\0' per entry."""
    fields = output.split("\0")
    changes = []
    index = 0
    while index < len(fields) and fields[index]:
        meta = fields[index].lstrip(":").split()
        path = fields[index + 1]
        changes.append(FileChange(path=path, old_mode=meta[0], new_mode=meta[1], status=meta[4]))
        index += 2
    return changes


def _path_problem(path: str) -> str:
    if not path or path.startswith("/") or "\\" in path or ".." in path.split("/") or re.match(r"^[A-Za-z]:", path):
        return f"unsafe path: {path!r}"
    if any(ord(char) < 32 for char in path):
        return f"control character in path: {path!r}"
    return ""


def _sensitive_reason(path: str) -> str:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name in DEPENDENCY_FILES:
        return f"dependency or build file: {path}"
    if name.startswith(".env") or lowered.endswith(SENSITIVE_SUFFIXES):
        return f"sensitive file type: {path}"
    tokens = set(re.split(r"[/._\-]", lowered)) - {""}
    hit = sorted(tokens & SENSITIVE_TOKENS)
    if hit:
        return f"sensitive path component {hit[0]!r}: {path}"
    return ""


def classify(changes: Sequence[FileChange], added_text: str) -> Decision:
    """Return ROUTINE only when every rule passes. Every failed rule adds a reason."""
    if not changes:
        return Decision(ESCALATE, ["no changed files to classify"])
    reasons = []
    if len(changes) > MAX_FILES:
        reasons.append(f"{len(changes)} files changed; the routine limit is {MAX_FILES}")
    for change in changes:
        problem = _path_problem(change.path)
        if problem:
            reasons.append(problem)
            continue
        if change.old_mode in (SYMLINK_MODE, SUBMODULE_MODE) or change.new_mode in (SYMLINK_MODE, SUBMODULE_MODE):
            reasons.append(f"symlink or submodule: {change.path}")
        if change.new_mode in EXECUTABLE_MODES:
            reasons.append(f"executable file: {change.path}")
        if not change.path.startswith(ROUTINE_PREFIXES):
            reasons.append(f"outside routine paths: {change.path}")
        sensitive = _sensitive_reason(change.path)
        if sensitive:
            reasons.append(sensitive)
    for pattern in SECRET_PATTERNS:
        if pattern.search(added_text):
            reasons.append(f"added text matches a credential pattern: {pattern.pattern[:40]}")
            break
    if reasons:
        return Decision(ESCALATE, sorted(set(reasons)))
    return Decision(ROUTINE, [])


def read_changes(base: str, head: str, repo: str = ".") -> tuple:
    """Return (changes, added_text) for base...head, read from git without a shell."""
    raw = _git(repo, "diff", "--raw", "-z", "--no-renames", f"{base}...{head}")
    patch = _git(repo, "diff", "--no-renames", "--no-color", "-U0", f"{base}...{head}")
    added = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    return parse_raw(raw), added


def _git(repo: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True, encoding="utf-8",
                            errors="replace")
    return result.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Classify a pull request as ROUTINE or ESCALATE.")
    parser.add_argument("--base", required=True, help="Base ref, for example origin/main.")
    parser.add_argument("--head", required=True, help="Head ref or SHA.")
    parser.add_argument("--repo", default=".", help="Repository path.")
    args = parser.parse_args(argv)
    changes, added = read_changes(args.base, args.head, args.repo)
    decision = classify(changes, added)
    print(json.dumps({"verdict": decision.verdict, "reasons": decision.reasons, "files": len(changes)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
