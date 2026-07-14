#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Python 3 was not found." >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(
        f"Python 3.10+ is required; current version is {sys.version.split()[0]}"
    )
PY

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

: "${PB_ALLOWED_SENDER:?Set PB_ALLOWED_SENDER to the exact trusted sender address}"
RUNTIME_ROOT="${PROJECT_BRAIN_RUNTIME_ROOT:-$HOME/.project-brain}"
mkdir -p "$RUNTIME_ROOT/results"
python bridge.py --once --output "$RUNTIME_ROOT/results/gmail-read-only-output.json"
