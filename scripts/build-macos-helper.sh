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
  "project-brain 0.8.0") ;;
  *)
    echo "unexpected helper version: $VERSION" >&2
    exit 1
    ;;
esac

CONTRACT="$($HELPER cli-contract --json)"
PROJECT_BRAIN_CONTRACT_JSON="$CONTRACT" "$PYTHON_BIN" - <<'PY'
import json
import os

response = json.loads(os.environ["PROJECT_BRAIN_CONTRACT_JSON"])
assert response["status"] == "ok"
assert len(response["document_sha256"]) == 64
contract = response["contract"]
assert contract["schema_version"] == 1
assert contract["contract_version"] == "1.1.0"
assert contract["core_version"] == "0.8.0"
native = contract["operations"]["native_onboarding"]
assert native["command_path"] == ["projects", "add"]
assert native["options"]["resolve_existing"] == "--resolve-existing"
local = contract["operations"]["local_task"]
assert local["request_schema_version"] == 1
assert local["transport"] == "stdin_json"
assert local["plan_command_path"] == ["tasks", "local-plan"]
assert local["create_command_path"] == ["tasks", "local-create"]
PY

"$HELPER" projects add --help | /usr/bin/grep -F -- "--resolve-existing" >/dev/null
"$HELPER" tasks local-plan --help | /usr/bin/grep -F -- "--json" >/dev/null
"$HELPER" tasks local-create --help | /usr/bin/grep -F -- "--plan-token" >/dev/null

echo "helper_path=$HELPER"
