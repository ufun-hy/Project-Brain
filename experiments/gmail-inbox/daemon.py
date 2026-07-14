#!/usr/bin/env python3
"""Deprecated one-shot compatibility launcher.

Scheduling belongs to launchd. This process executes one Bridge apply and exits
so the next launch loads current code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

raise SystemExit(
    subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "bridge_v2.py"), "--apply"],
        cwd=ROOT,
        text=True,
    ).returncode
)
