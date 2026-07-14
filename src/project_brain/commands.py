"""Small subprocess boundary shared by Core adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import ExternalCommandError
from .security import redact_text


def run_command(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    timeout: int = 1800,
    check: bool = True,
    retryable: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ExternalCommandError(f"Command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalCommandError(
            f"Command timed out after {timeout}s: {args[0]}", retryable=True
        ) from exc
    if check and completed.returncode != 0:
        detail = redact_text((completed.stderr or completed.stdout).strip())[-4000:]
        raise ExternalCommandError(
            f"Command failed ({completed.returncode}): {' '.join(args)}\n{detail}",
            retryable=retryable,
            returncode=completed.returncode,
        )
    return completed


def git(
    repo: str | Path,
    *args: str,
    check: bool = True,
    retryable: bool = False,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        ["git", "-C", str(repo), *args],
        check=check,
        retryable=retryable,
        timeout=timeout,
    )
