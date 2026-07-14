"""OS process-group supervision shared by execution and recovery."""

from __future__ import annotations

import os
import signal
import subprocess
import time


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


def terminate_process_group(
    *,
    child_pid: int | None,
    child_pgid: int | None,
    grace_seconds: float = 5.0,
    process: subprocess.Popen[str] | None = None,
) -> bool:
    """Terminate, then kill, a child-owned group and confirm it has exited."""
    pgid = child_pgid or child_pid
    if not pgid or pgid <= 0:
        return True
    if pgid == os.getpgrp():
        raise RuntimeError("refusing to terminate the Bridge process group")

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
