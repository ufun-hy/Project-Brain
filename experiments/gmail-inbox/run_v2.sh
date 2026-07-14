#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv; run the original Gmail bridge setup first." >&2
  exit 1
fi

: "${PB_ALLOWED_SENDER:?Set PB_ALLOWED_SENDER to the exact trusted sender address}"

case "${1:-dry-run}" in
  dry-run)
    exec .venv/bin/python bridge_v2.py
    ;;
  apply)
    exec .venv/bin/python bridge_v2.py --apply
    ;;
  daemon)
    echo "daemon mode is one-shot; schedule this command with launchd" >&2
    exec .venv/bin/python bridge_v2.py --apply
    ;;
  *)
    echo "Usage: ./run_v2.sh [dry-run|apply|daemon]" >&2
    exit 1
    ;;
esac
