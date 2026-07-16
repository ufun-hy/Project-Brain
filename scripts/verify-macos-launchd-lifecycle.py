#!/usr/bin/env python3
"""Exercise the fixed Product Brain services against the real macOS launchd."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from project_brain.runtime import RuntimePaths
from project_brain.services import ServiceManager


def wait_for_status(manager: ServiceManager, expected: str, *, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    latest = manager.status()
    while latest["status"] != expected and time.monotonic() < deadline:
        time.sleep(0.25)
        latest = manager.status()
    if latest["status"] != expected:
        raise RuntimeError(f"expected service status {expected}, got {latest}")
    return latest


def main() -> None:
    helper_value = os.environ.get("PROJECT_BRAIN_HELPER")
    if not helper_value:
        raise RuntimeError("PROJECT_BRAIN_HELPER is required")
    helper = Path(helper_value).expanduser().resolve()
    if not helper.is_file() or not os.access(helper, os.X_OK):
        raise RuntimeError("PROJECT_BRAIN_HELPER must be an executable file")

    with tempfile.TemporaryDirectory(prefix="project-brain-launchd-") as temporary:
        root = Path(temporary)
        runtime = RuntimePaths.from_value(root / "runtime")
        manager = ServiceManager(
            runtime,
            helper_path=helper,
            launch_agents_dir=root / "LaunchAgents",
        )
        marker = runtime.root / "preserved.txt"
        try:
            manager.install()
            installed = wait_for_status(manager, "healthy")
            marker.write_text("preserve\n", encoding="utf-8")

            manager.stop()
            stopped = wait_for_status(manager, "stopped")

            manager.start()
            restarted = wait_for_status(manager, "healthy")

            result = manager.uninstall()
            uninstalled = wait_for_status(manager, "not_installed")
            if marker.read_text(encoding="utf-8") != "preserve\n":
                raise RuntimeError("service uninstall changed runtime data")
            if not result["runtime_preserved"]:
                raise RuntimeError("service uninstall did not report runtime preservation")
        finally:
            try:
                manager.uninstall()
            except Exception:
                pass

        print(
            json.dumps(
                {
                    "status": "passed",
                    "installed": installed["status"],
                    "stopped": stopped["status"],
                    "restarted": restarted["status"],
                    "uninstalled": uninstalled["status"],
                    "runtime_preserved": True,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
