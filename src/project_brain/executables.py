"""Resolve the small fixed set of local product prerequisites."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


MACOS_TOOL_DIRECTORIES = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)

LAUNCHD_TOOL_PATH = ":".join(str(path) for path in MACOS_TOOL_DIRECTORIES)


def find_executable(value: str) -> str | None:
    """Return a canonical executable from PATH or the fixed macOS product paths."""
    candidate = shutil.which(str(Path(value).expanduser()))
    if candidate is not None:
        resolved = Path(candidate).resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    if "/" in value or (os.path.altsep is not None and os.path.altsep in value):
        return None
    directories = (*MACOS_TOOL_DIRECTORIES, Path.home() / ".local" / "bin")
    for directory in directories:
        candidate_path = directory / value
        if candidate_path.is_file() and os.access(candidate_path, os.X_OK):
            return str(candidate_path.resolve())
    return None
