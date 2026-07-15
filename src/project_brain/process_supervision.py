"""OS process-group supervision shared by execution and recovery."""

from __future__ import annotations

from enum import Enum
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any


class ProcessIdentityState(str, Enum):
    DEAD = "dead"
    VERIFIED_ALIVE = "verified_alive"
    UNVERIFIED_ALIVE = "unverified_alive"


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_group_alive(pgid: int | None) -> bool:
    if not pgid or pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def agent_process_group_alive(child_pid: int | None, child_pgid: int | None) -> bool:
    """Treat any surviving member of the persisted child group as active."""
    return process_group_alive(child_pgid) or process_alive(child_pid)


def _ps_value(pid: int, field: str) -> str | None:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", f"{field}="],
        check=False,
        text=True,
        capture_output=True,
    )
    value = completed.stdout.strip()
    return value or None


def _linux_identity(pid: int) -> tuple[str, str, str] | None:
    proc = Path("/proc") / str(pid)
    try:
        stat = (proc / "stat").read_text(encoding="utf-8")
        remainder = stat[stat.rfind(")") + 2 :].split()
        start_ticks = remainder[19]
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        executable = str((proc / "exe").resolve(strict=True))
        command = (proc / "cmdline").read_bytes()
    except (FileNotFoundError, IndexError, OSError):
        return None
    return f"{boot_id}:{start_ticks}", executable, hashlib.sha256(command).hexdigest()


def _portable_identity(pid: int) -> tuple[str, str, str] | None:
    started = _ps_value(pid, "lstart")
    executable = _ps_value(pid, "comm")
    command = _ps_value(pid, "command")
    if not started or not executable or not command:
        return None
    return started, executable, hashlib.sha256(command.encode("utf-8")).hexdigest()


def capture_process_identity(
    child_pid: int | None,
    child_pgid: int | None = None,
) -> dict[str, Any] | None:
    """Capture stable-enough process birth and executable markers for later signals."""
    if not child_pid or child_pid <= 0 or not process_alive(child_pid):
        return None
    try:
        actual_pgid = os.getpgid(child_pid)
    except ProcessLookupError:
        return None
    if child_pgid and actual_pgid != child_pgid:
        return None
    captured = _linux_identity(child_pid) if Path("/proc").is_dir() else None
    if captured is None:
        captured = _portable_identity(child_pid)
    if captured is None:
        return None
    start_marker, executable, command_digest = captured
    return {
        "pid": child_pid,
        "pgid": actual_pgid,
        "start_marker": start_marker,
        "executable": executable,
        "command_digest": command_digest,
    }


def process_identity_matches(
    child_pid: int | None,
    child_pgid: int | None,
    expected_identity: dict[str, Any] | None,
) -> bool:
    if not expected_identity:
        return False
    current = capture_process_identity(child_pid, child_pgid)
    if current is None:
        return False
    required = ("pid", "pgid", "start_marker", "executable", "command_digest")
    return all(current.get(key) == expected_identity.get(key) for key in required)


def inspect_agent_process_group(
    child_pid: int | None,
    child_pgid: int | None,
    expected_identity: dict[str, Any] | None,
) -> ProcessIdentityState:
    if not agent_process_group_alive(child_pid, child_pgid):
        return ProcessIdentityState.DEAD
    if process_identity_matches(child_pid, child_pgid, expected_identity):
        return ProcessIdentityState.VERIFIED_ALIVE
    return ProcessIdentityState.UNVERIFIED_ALIVE


def terminate_process_group(
    *,
    child_pid: int | None,
    child_pgid: int | None,
    expected_identity: dict[str, Any] | None = None,
    grace_seconds: float = 5.0,
    process: subprocess.Popen[str] | None = None,
) -> bool:
    """Signal only an identity-verified child group, then confirm its exit."""
    pgid = child_pgid or child_pid
    if not pgid or pgid <= 0:
        return True
    if pgid == os.getpgrp():
        raise RuntimeError("refusing to terminate the Bridge process group")
    if not agent_process_group_alive(child_pid, child_pgid):
        if process is not None and process.poll() is None:
            process.wait(timeout=max(0.1, grace_seconds))
        return True
    direct_child_proof = (
        process is not None and process.pid == child_pid and process.poll() is None
    )
    if expected_identity is not None:
        if not process_identity_matches(child_pid, child_pgid, expected_identity):
            return False
    elif not direct_child_proof:
        return False

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        if process is not None:
            process.wait(timeout=max(0.1, grace_seconds))
        return True

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            break
        if not process_group_alive(pgid):
            break
        time.sleep(0.05)

    if process_group_alive(pgid):
        if expected_identity is not None and not process_identity_matches(
            child_pid, child_pgid, expected_identity
        ):
            return False
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process is not None:
        try:
            process.wait(timeout=max(1.0, grace_seconds))
        except subprocess.TimeoutExpired:
            return False

    deadline = time.monotonic() + max(1.0, grace_seconds)
    while time.monotonic() < deadline and process_group_alive(pgid):
        time.sleep(0.05)
    return not process_group_alive(pgid)
