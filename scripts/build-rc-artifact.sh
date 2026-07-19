#!/bin/sh
set -eu

ROOT=$(/usr/bin/git rev-parse --show-toplevel)
PROJECT="$ROOT/apps/macos/ProjectBrain/ProjectBrain.xcodeproj"
OUTPUT_DIR=${PROJECT_BRAIN_RC_OUTPUT_DIR:?PROJECT_BRAIN_RC_OUTPUT_DIR is required}
DERIVED_DATA=${PROJECT_BRAIN_RC_DERIVED_DATA:?PROJECT_BRAIN_RC_DERIVED_DATA is required}
HELPER=${PROJECT_BRAIN_BUNDLED_HELPER:?PROJECT_BRAIN_BUNDLED_HELPER is required}
CI_RUN_URL=${PROJECT_BRAIN_CI_RUN_URL:-local_unpublished_build}
APP_VERSION=0.8.0
APP_BUILD=8
ARCHITECTURE=arm64
ARTIFACT_BASE=Project-Brain-Local-Tasks-Build8-arm64
INSTALL_GUIDE_NAME="把 Project Brain.app 拖到 Applications 安装.txt"
INSTALL_GUIDE="$ROOT/packaging/dmg/$INSTALL_GUIDE_NAME"

if [ ! -x "$HELPER" ]; then
  echo "error: self-contained Core helper is missing or not executable" >&2
  exit 1
fi
if [ "$("$HELPER" --version)" != "project-brain 0.8.0" ]; then
  echo "error: self-contained Core helper version does not match Build 8" >&2
  exit 1
fi

/bin/mkdir -p "$OUTPUT_DIR"
/usr/bin/xcodebuild \
  -project "$PROJECT" \
  -scheme ProjectBrain \
  -configuration Release \
  -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP="$DERIVED_DATA/Build/Products/Release/Project Brain.app"
if [ ! -d "$APP" ]; then
  echo "error: Release app bundle was not produced" >&2
  exit 1
fi
if [ ! -x "$APP/Contents/Resources/project-brain" ]; then
  echo "error: Release app does not contain the self-contained Core helper" >&2
  exit 1
fi
if [ ! -f "$APP/Contents/Resources/project-brain-cli-contract.json" ]; then
  echo "error: Release app does not contain the Core CLI contract" >&2
  exit 1
fi
if ! /usr/bin/cmp -s \
  "$ROOT/src/project_brain/cli_contract.json" \
  "$APP/Contents/Resources/project-brain-cli-contract.json"; then
  echo "error: Release app Core CLI contract is not canonical" >&2
  exit 1
fi
if [ ! -f "$APP/Contents/Resources/tunnel-client-compatibility.json" ]; then
  echo "error: Release app does not contain the static Tunnel compatibility manifest" >&2
  exit 1
fi
if [ -e "$APP/Contents/Resources/tunnel-client" ]; then
  echo "error: Tunnel Client must not be bundled in Project Brain.app" >&2
  exit 1
fi
if [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")" != "$APP_BUILD" ]; then
  echo "error: Release app build number does not match RC artifact" >&2
  exit 1
fi
if [ "$(/usr/libexec/PlistBuddy -c 'Print :LSMultipleInstancesProhibited' "$APP/Contents/Info.plist")" != "true" ]; then
  echo "error: Release app does not prohibit multiple instances" >&2
  exit 1
fi
if [ ! -f "$INSTALL_GUIDE" ]; then
  echo "error: DMG installation guide is missing" >&2
  exit 1
fi

/usr/bin/python3 - \
  "$APP/Contents/Resources/project-brain" \
  "$APP/Contents/Resources/project-brain-cli-contract.json" <<'PY'
import hashlib
import json
import subprocess
import sys

helper, contract_path = sys.argv[1:]
contract_bytes = open(contract_path, "rb").read()
contract = json.loads(contract_bytes)
reported = json.loads(subprocess.run(
    [helper, "cli-contract", "--json"],
    check=True,
    capture_output=True,
    text=True,
).stdout)
assert reported["status"] == "ok"
assert reported["contract"] == contract
assert reported["document_sha256"] == hashlib.sha256(contract_bytes).hexdigest()
assert contract["schema_version"] == 1
assert contract["contract_version"] == "1.1.0"
assert contract["core_version"] == "0.8.0"
assert contract["operations"]["native_onboarding"]["options"]["resolve_existing"] == "--resolve-existing"
local = contract["operations"]["local_task"]
assert local["request_schema_version"] == 1
assert local["transport"] == "stdin_json"
assert local["plan_command_path"] == ["tasks", "local-plan"]
assert local["create_command_path"] == ["tasks", "local-create"]
PY

/usr/bin/python3 "$ROOT/scripts/verify-bundled-helper-onboarding.py" "$APP"

MANIFEST_VERSION=$(/usr/bin/python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["schema_version"])' \
  "$APP/Contents/Resources/tunnel-client-compatibility.json")
if [ "$MANIFEST_VERSION" != "1" ]; then
  echo "error: unexpected Tunnel compatibility manifest version" >&2
  exit 1
fi

TEMP_ROOT=$(/usr/bin/mktemp -d "${RUNNER_TEMP:-/tmp}/project-brain-rc1.XXXXXX")
trap '/bin/rm -rf "$TEMP_ROOT"' EXIT INT TERM
/bin/mkdir -p "$TEMP_ROOT/dmg"
/usr/bin/ditto "$APP" "$TEMP_ROOT/dmg/Project Brain.app"
/bin/ln -s /Applications "$TEMP_ROOT/dmg/Applications"
/usr/bin/ditto "$INSTALL_GUIDE" "$TEMP_ROOT/dmg/$INSTALL_GUIDE_NAME"

DMG="$OUTPUT_DIR/$ARTIFACT_BASE.dmg"
ZIP="$OUTPUT_DIR/$ARTIFACT_BASE.zip"
/usr/bin/hdiutil create \
  -quiet \
  -volname "Project Brain Local Tasks Build 8" \
  -srcfolder "$TEMP_ROOT/dmg" \
  -format UDZO \
  -ov \
  "$DMG"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

HEAD_SHA=$(/usr/bin/git -C "$ROOT" rev-parse HEAD)
APP_EXECUTABLE_SHA=$(/usr/bin/shasum -a 256 "$APP/Contents/MacOS/Project Brain" | /usr/bin/awk '{print $1}')
HELPER_SHA=$(/usr/bin/shasum -a 256 "$APP/Contents/Resources/project-brain" | /usr/bin/awk '{print $1}')
CLI_CONTRACT_SHA=$(/usr/bin/shasum -a 256 "$APP/Contents/Resources/project-brain-cli-contract.json" | /usr/bin/awk '{print $1}')
DMG_SHA=$(/usr/bin/shasum -a 256 "$DMG" | /usr/bin/awk '{print $1}')
ZIP_SHA=$(/usr/bin/shasum -a 256 "$ZIP" | /usr/bin/awk '{print $1}')
MANIFEST="$OUTPUT_DIR/build-manifest.json"

APP_VERSION="$APP_VERSION" \
APP_BUILD="$APP_BUILD" \
HEAD_SHA="$HEAD_SHA" \
APP_EXECUTABLE_SHA="$APP_EXECUTABLE_SHA" \
HELPER_SHA="$HELPER_SHA" \
CLI_CONTRACT_SHA="$CLI_CONTRACT_SHA" \
MANIFEST_VERSION="$MANIFEST_VERSION" \
ARCHITECTURE="$ARCHITECTURE" \
CI_RUN_URL="$CI_RUN_URL" \
DMG_NAME=$(/usr/bin/basename "$DMG") \
DMG_SHA="$DMG_SHA" \
ZIP_NAME=$(/usr/bin/basename "$ZIP") \
ZIP_SHA="$ZIP_SHA" \
OUTPUT_MANIFEST="$MANIFEST" \
/usr/bin/python3 - <<'PY'
import json
import os

manifest = {
    "schema_version": 3,
    "artifact_classification": "unsigned_internal_rc",
    "app": {
        "version": os.environ["APP_VERSION"],
        "build": os.environ["APP_BUILD"],
        "executable_sha256": os.environ["APP_EXECUTABLE_SHA"],
    },
    "git_head_sha": os.environ["HEAD_SHA"],
    "core_helper": {
        "version": "0.8.0",
        "sha256": os.environ["HELPER_SHA"],
    },
    "core_cli_contract": {
        "schema_version": 1,
        "contract_version": "1.1.0",
        "core_version": "0.8.0",
        "document_sha256": os.environ["CLI_CONTRACT_SHA"],
    },
    "local_task_contract": {
        "task_request_schema_version": 1,
        "result_schema_version": 1,
        "database_schema_version": 9,
        "transport": "stdin_json",
        "plan_token_prefix": "local-v1:",
    },
    "tunnel_compatibility_manifest_version": int(os.environ["MANIFEST_VERSION"]),
    "supported_tunnel_client_versions": ["0.0.10"],
    "target_architecture": os.environ["ARCHITECTURE"],
    "signing_status": "unsigned_internal_rc",
    "notarization_status": "not_notarized",
    "ci_run_url": os.environ["CI_RUN_URL"],
    "external_acceptance": "pending_user_credentials_and_actions",
    "artifacts": [
        {"name": os.environ["DMG_NAME"], "sha256": os.environ["DMG_SHA"]},
        {"name": os.environ["ZIP_NAME"], "sha256": os.environ["ZIP_SHA"]},
    ],
}
with open(os.environ["OUTPUT_MANIFEST"], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

{
  /usr/bin/shasum -a 256 "$DMG"
  /usr/bin/shasum -a 256 "$ZIP"
  /usr/bin/shasum -a 256 "$MANIFEST"
} | /usr/bin/sed "s|$OUTPUT_DIR/||" > "$OUTPUT_DIR/SHA256SUMS"

echo "Build 8 artifact directory: $OUTPUT_DIR"
echo "Build 8 DMG SHA-256: $DMG_SHA"
echo "Build 8 classification: unsigned_internal_rc; not notarized"
echo "External acceptance: pending; this build did not use real ChatGPT ingress"
