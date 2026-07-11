#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INTERVAL = 60

while True:
    result = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "bridge_v2.py"), "--apply"],
        cwd=ROOT,
        text=True,
    )
    if result.returncode not in (0, 2):
        print(f"bridge exited with {result.returncode}", file=sys.stderr)
    time.sleep(INTERVAL)
