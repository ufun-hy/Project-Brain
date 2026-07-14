"""Non-Codex task actions, constrained to an isolated worktree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .commands import run_command
from .errors import InvalidPathError, InvalidTaskError, TransientTaskError


def safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts:
        raise InvalidPathError(f"Invalid relative path: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidPathError(f"Path traversal is forbidden: {value}")
    if path.parts[0] == ".git":
        raise InvalidPathError("Writing inside .git is forbidden")
    return path


def write_files(worktree: str | Path, payload: dict[str, Any]) -> list[str]:
    root = Path(worktree).resolve()
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise InvalidTaskError("write_files task requires a non-empty files array")
    changed: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise InvalidTaskError("Each files item must be an object")
        relative = safe_relative_path(str(item.get("path", "")))
        content = item.get("content")
        if not isinstance(content, str):
            raise InvalidTaskError(f"content must be a string for {relative}")
        target = (root / relative).resolve()
        if root not in target.parents:
            raise InvalidPathError(f"Target escapes task worktree: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed.append(str(relative))
    return changed


def run_named_command(
    worktree: str | Path,
    payload: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    name = payload.get("command")
    allowed = project.get("allowed_commands") or {}
    if not isinstance(name, str) or name not in allowed:
        raise InvalidTaskError(f"Command is not allowlisted: {name}")
    argv = allowed[name]
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise InvalidTaskError(f"Invalid allowlisted command definition: {name}")
    timeout = int(payload.get("timeout_seconds", 900))
    try:
        completed = run_command(argv, cwd=worktree, timeout=timeout)
    except Exception as exc:
        if getattr(exc, "retryable", False):
            raise TransientTaskError(str(exc)) from exc
        raise
    return {
        "command": name,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }
