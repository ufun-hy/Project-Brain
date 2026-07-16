#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DIST_ROOT="${PROJECT_BRAIN_HELPER_DIST:-$ROOT/build/macos-helper/dist}"
WORK_ROOT="${PROJECT_BRAIN_HELPER_WORK:-$ROOT/build/macos-helper/work}"
SPEC="$ROOT/packaging/pyinstaller/project-brain.spec"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_ROOT" \
  --workpath "$WORK_ROOT" \
  "$SPEC"

HELPER="$DIST_ROOT/project-brain"
test -x "$HELPER"
VERSION="$($HELPER --version)"
case "$VERSION" in
  "project-brain 0.6.0") ;;
  *)
    echo "unexpected helper version: $VERSION" >&2
    exit 1
    ;;
esac

echo "helper_path=$HELPER"
