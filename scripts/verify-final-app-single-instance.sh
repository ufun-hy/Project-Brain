#!/bin/sh
set -eu

if [ "${CI:-}" != "true" ]; then
  echo "error: final app instance verification is restricted to an isolated CI runner" >&2
  exit 1
fi

DMG=${1:?usage: verify-final-app-single-instance.sh /path/to/artifact.dmg}
ROOT=$(/usr/bin/mktemp -d "${RUNNER_TEMP:-/tmp}/project-brain-instance.XXXXXX")
MOUNT="$ROOT/mount"
INSTALLED_APP="/Applications/Project Brain.app"
FIRST_PID=
SECOND_PID=
ATTACHED=false
INSTALLED=false

cleanup() {
  if [ -n "$SECOND_PID" ]; then
    /bin/kill "$SECOND_PID" 2>/dev/null || true
    wait "$SECOND_PID" 2>/dev/null || true
  fi
  if [ -n "$FIRST_PID" ]; then
    /bin/kill "$FIRST_PID" 2>/dev/null || true
    wait "$FIRST_PID" 2>/dev/null || true
  fi
  if [ "$INSTALLED" = true ]; then
    /bin/rm -rf "$INSTALLED_APP"
  fi
  if [ "$ATTACHED" = true ]; then
    /usr/bin/hdiutil detach -quiet "$MOUNT" || true
  fi
  /bin/rm -rf "$ROOT"
}
trap cleanup EXIT INT TERM

if [ -e "$INSTALLED_APP" ]; then
  echo "error: refusing to replace a pre-existing /Applications/Project Brain.app" >&2
  exit 1
fi

/bin/mkdir -p "$MOUNT"
/usr/bin/hdiutil attach -quiet -readonly -nobrowse -mountpoint "$MOUNT" "$DMG"
ATTACHED=true
/usr/bin/ditto "$MOUNT/Project Brain.app" "$INSTALLED_APP"
INSTALLED=true

LOCK="$ROOT/app-instance.lock"
PROBE="$ROOT/ui-probe.json"
INSTALLED_EXECUTABLE="$INSTALLED_APP/Contents/MacOS/Project Brain"
DMG_EXECUTABLE="$MOUNT/Project Brain.app/Contents/MacOS/Project Brain"

CI=true \
PROJECT_BRAIN_UI_TEST_MODE=1 \
PROJECT_BRAIN_INSTANCE_LOCK_PATH="$LOCK" \
PROJECT_BRAIN_UI_PROBE_PATH="$PROBE" \
"$INSTALLED_EXECUTABLE" &
FIRST_PID=$!

ready=false
attempt=0
while [ "$attempt" -lt 80 ]; do
  if [ -f "$PROBE" ] && /usr/bin/python3 - "$PROBE" "$FIRST_PID" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if value == {
    "management_window_count": 1,
    "pid": int(sys.argv[2]),
} else 1)
PY
  then
    ready=true
    break
  fi
  /bin/sleep 0.25
  attempt=$((attempt + 1))
done
if [ "$ready" != true ]; then
  echo "error: installed final app did not report exactly one management window" >&2
  exit 1
fi

CI=true \
PROJECT_BRAIN_UI_TEST_MODE=1 \
PROJECT_BRAIN_INSTANCE_LOCK_PATH="$LOCK" \
PROJECT_BRAIN_UI_PROBE_PATH="$PROBE" \
"$DMG_EXECUTABLE" &
SECOND_PID=$!

attempt=0
while /bin/kill -0 "$SECOND_PID" 2>/dev/null && [ "$attempt" -lt 40 ]; do
  /bin/sleep 0.25
  attempt=$((attempt + 1))
done
if /bin/kill -0 "$SECOND_PID" 2>/dev/null; then
  echo "error: DMG copy remained running beside the Applications copy" >&2
  exit 1
fi
wait "$SECOND_PID" || true
SECOND_PID=

/bin/kill -0 "$FIRST_PID"
/usr/bin/python3 - "$PROBE" "$FIRST_PID" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["pid"] == int(sys.argv[2])
assert value["management_window_count"] == 1
PY

echo "Final DMG and Applications copies are limited to one process and one management window"
