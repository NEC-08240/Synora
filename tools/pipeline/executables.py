"""Find the git and Claude Code executables the bridge runs.

Order for each tool: an explicit path in an environment variable, then PATH lookup.
Nothing is downloaded or installed. A missing tool raises ExecutableNotFound with the fix.
"""

import os
import shutil
from pathlib import Path

GIT_ENV = "SYNORA_BRIDGE_GIT"
CLAUDE_ENV = "SYNORA_BRIDGE_CLAUDE"


class ExecutableNotFound(RuntimeError):
    pass


def resolve_executable(name, env_var, environ=os.environ, which=shutil.which):
    configured = environ.get(env_var, "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise ExecutableNotFound(
                f"{env_var} is set to '{configured}', which is not a file. "
                f"Set it to the full path of {name}."
            )
        return str(path.resolve())
    found = which(name)
    if found:
        return found
    raise ExecutableNotFound(
        f"'{name}' was not found on PATH. Install it, or set {env_var} to its full path."
    )


def resolve_executables(environ=os.environ, which=shutil.which):
    return {
        "git": resolve_executable("git", GIT_ENV, environ, which),
        "claude": resolve_executable("claude", CLAUDE_ENV, environ, which),
    }
