#!/bin/sh
set -eu

ROOT=$(/usr/bin/git rev-parse --show-toplevel)
OUTPUT_DIR=${PROJECT_BRAIN_RELEASE_OUTPUT_DIR:?PROJECT_BRAIN_RELEASE_OUTPUT_DIR is required}
DERIVED_DATA=${PROJECT_BRAIN_RELEASE_DERIVED_DATA:?PROJECT_BRAIN_RELEASE_DERIVED_DATA is required}
HELPER=${PROJECT_BRAIN_BUNDLED_HELPER:?PROJECT_BRAIN_BUNDLED_HELPER is required}
SIGNING_IDENTITY=${PROJECT_BRAIN_SIGNING_IDENTITY:?PROJECT_BRAIN_SIGNING_IDENTITY is required}
TEAM_ID=${PROJECT_BRAIN_TEAM_ID:?PROJECT_BRAIN_TEAM_ID is required}
NOTARY_KEY_PATH=${PROJECT_BRAIN_NOTARY_KEY_PATH:?PROJECT_BRAIN_NOTARY_KEY_PATH is required}
NOTARY_KEY_ID=${PROJECT_BRAIN_NOTARY_KEY_ID:?PROJECT_BRAIN_NOTARY_KEY_ID is required}
NOTARY_ISSUER_ID=${PROJECT_BRAIN_NOTARY_ISSUER_ID:?PROJECT_BRAIN_NOTARY_ISSUER_ID is required}
CI_RUN_URL=${PROJECT_BRAIN_CI_RUN_URL:?PROJECT_BRAIN_CI_RUN_URL is required}
APP_VERSION=0.8.0
APP_BUILD=10
ARCHITECTURE=arm64
ARTIFACT_BASE=Project-Brain-Build10-arm64
INSTALL_GUIDE_NAME="把 Project Brain.app 拖到 Applications 安装.txt"
INSTALL_GUIDE="$ROOT/packaging/dmg/$INSTALL_GUIDE_NAME"

case "$SIGNING_IDENTITY" in
  "Developer ID Application:"*) ;;
  *)
    echo "error: PROJECT_BRAIN_SIGNING_IDENTITY must be a Developer ID Application identity" >&2
    exit 1
    ;;
esac
if ! /usr/bin/security find-identity -v -p codesigning |
  /usr/bin/grep -F "\"$SIGNING_IDENTITY\"" >/dev/null; then
  echo "error: configured Developer ID Application identity is not installed" >&2
  exit 1
fi
if [ ! -f "$NOTARY_KEY_PATH" ]; then
  echo "error: App Store Connect notary API key is missing" >&2
  exit 1
fi
if [ ! -x "$HELPER" ]; then
  echo "error: self-contained Core helper is missing or not executable" >&2
  exit 1
fi
if [ -e "$OUTPUT_DIR" ]; then
  echo "error: Build 10 output already exists; refusing to overwrite immutable artifacts" >&2
  exit 1
fi

TEMP_ROOT=$(/usr/bin/mktemp -d "${RUNNER_TEMP:-/tmp}/project-brain-build10.XXXXXX")
trap '/bin/rm -rf "$TEMP_ROOT"' EXIT INT TERM
STAGING_OUTPUT="$TEMP_ROOT/final"
/bin/mkdir -p "$STAGING_OUTPUT"

PROJECT_BRAIN_RC_OUTPUT_DIR="$TEMP_ROOT/unsigned-preflight" \
PROJECT_BRAIN_RC_DERIVED_DATA="$DERIVED_DATA" \
PROJECT_BRAIN_BUNDLED_HELPER="$HELPER" \
PROJECT_BRAIN_CI_RUN_URL="$CI_RUN_URL" \
  "$ROOT/scripts/build-rc-artifact.sh"

APP="$DERIVED_DATA/Build/Products/Release/Project Brain.app"
APP_HELPER="$APP/Contents/Resources/project-brain"
APP_CONTRACT="$APP/Contents/Resources/project-brain-cli-contract.json"
if [ ! -d "$APP" ] || [ ! -x "$APP_HELPER" ]; then
  echo "error: validated Release App and embedded helper are required" >&2
  exit 1
fi

# Sign from the innermost executable out. Never use --deep to create signatures.
/usr/bin/codesign \
  --force \
  --sign "$SIGNING_IDENTITY" \
  --options runtime \
  --timestamp \
  "$APP_HELPER"

APP_MAIN="$APP/Contents/MacOS/Project Brain"
/usr/bin/find "$APP/Contents" -type f -perm -111 -print |
  while IFS= read -r NESTED_EXECUTABLE; do
    if [ "$NESTED_EXECUTABLE" = "$APP_HELPER" ] ||
      [ "$NESTED_EXECUTABLE" = "$APP_MAIN" ]; then
      continue
    fi
    if /usr/bin/file -b "$NESTED_EXECUTABLE" | /usr/bin/grep -F "Mach-O" >/dev/null; then
      /usr/bin/codesign \
        --force \
        --sign "$SIGNING_IDENTITY" \
        --options runtime \
        --timestamp \
        "$NESTED_EXECUTABLE"
    fi
  done

for NESTED_DIRECTORY in \
  "$APP/Contents/Frameworks" \
  "$APP/Contents/PlugIns" \
  "$APP/Contents/XPCServices"; do
  if [ ! -d "$NESTED_DIRECTORY" ]; then
    continue
  fi
  /usr/bin/find "$NESTED_DIRECTORY" -depth -type d \
    \( -name "*.framework" -o -name "*.xpc" -o -name "*.appex" -o -name "*.app" \) \
    -print |
    while IFS= read -r NESTED_BUNDLE; do
      /usr/bin/codesign \
        --force \
        --sign "$SIGNING_IDENTITY" \
        --options runtime \
        --timestamp \
        "$NESTED_BUNDLE"
    done
done

/usr/bin/codesign \
  --force \
  --sign "$SIGNING_IDENTITY" \
  --options runtime \
  --timestamp \
  "$APP"

/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
/usr/bin/codesign --verify --strict --verbose=2 "$APP_HELPER"
/usr/bin/codesign -d --verbose=4 "$APP" >"$TEMP_ROOT/app-codesign.txt" 2>&1
/usr/bin/codesign -d --verbose=4 "$APP_HELPER" >"$TEMP_ROOT/helper-codesign.txt" 2>&1
for SIGNATURE_REPORT in "$TEMP_ROOT/app-codesign.txt" "$TEMP_ROOT/helper-codesign.txt"; do
  /usr/bin/grep -F "TeamIdentifier=$TEAM_ID" "$SIGNATURE_REPORT" >/dev/null
  /usr/bin/grep -F "Runtime Version" "$SIGNATURE_REPORT" >/dev/null
  /usr/bin/grep -F "Timestamp=" "$SIGNATURE_REPORT" >/dev/null
done
if /usr/bin/codesign -d --entitlements :- "$APP" 2>/dev/null |
  /usr/bin/grep -F "com.apple.security.get-task-allow" >/dev/null; then
  echo "error: release App signature contains the development get-task-allow entitlement" >&2
  exit 1
fi

APP_NOTARY_ZIP="$TEMP_ROOT/Project-Brain-Build10-notary.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP_NOTARY_ZIP"
/usr/bin/xcrun notarytool submit "$APP_NOTARY_ZIP" \
  --key "$NOTARY_KEY_PATH" \
  --key-id "$NOTARY_KEY_ID" \
  --issuer "$NOTARY_ISSUER_ID" \
  --wait \
  --output-format json >"$TEMP_ROOT/app-notary-raw.json"

APP_SUBMISSION_ID=$(/usr/bin/python3 - "$TEMP_ROOT/app-notary-raw.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("status") != "Accepted" or not payload.get("id"):
    raise SystemExit(f"App notarization was not accepted: {payload.get('status', 'unknown')}")
print(payload["id"])
PY
)
/usr/bin/xcrun stapler staple "$APP"
/usr/bin/xcrun stapler validate "$APP"
/usr/sbin/spctl --assess --type execute --verbose=4 "$APP"

APP_ZIP="$STAGING_OUTPUT/$ARTIFACT_BASE.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP_ZIP"

/bin/mkdir -p "$TEMP_ROOT/dmg"
/usr/bin/ditto "$APP" "$TEMP_ROOT/dmg/Project Brain.app"
/bin/ln -s /Applications "$TEMP_ROOT/dmg/Applications"
/usr/bin/ditto "$INSTALL_GUIDE" "$TEMP_ROOT/dmg/$INSTALL_GUIDE_NAME"

DMG="$STAGING_OUTPUT/$ARTIFACT_BASE.dmg"
/usr/bin/hdiutil create \
  -quiet \
  -volname "Project Brain Build 10" \
  -srcfolder "$TEMP_ROOT/dmg" \
  -format UDZO \
  "$DMG"
/usr/bin/codesign \
  --force \
  --sign "$SIGNING_IDENTITY" \
  --timestamp \
  "$DMG"
/usr/bin/codesign --verify --strict --verbose=2 "$DMG"

/usr/bin/xcrun notarytool submit "$DMG" \
  --key "$NOTARY_KEY_PATH" \
  --key-id "$NOTARY_KEY_ID" \
  --issuer "$NOTARY_ISSUER_ID" \
  --wait \
  --output-format json >"$TEMP_ROOT/dmg-notary-raw.json"

DMG_SUBMISSION_ID=$(/usr/bin/python3 - "$TEMP_ROOT/dmg-notary-raw.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("status") != "Accepted" or not payload.get("id"):
    raise SystemExit(f"DMG notarization was not accepted: {payload.get('status', 'unknown')}")
print(payload["id"])
PY
)
/usr/bin/xcrun stapler staple "$DMG"
/usr/bin/xcrun stapler validate "$DMG"
/usr/sbin/spctl \
  --assess \
  --type open \
  --context context:primary-signature \
  --verbose=4 \
  "$DMG"

APP_RECEIPT="$STAGING_OUTPUT/app-notarization.json"
DMG_RECEIPT="$STAGING_OUTPUT/dmg-notarization.json"
APP_SUBMISSION_ID="$APP_SUBMISSION_ID" \
DMG_SUBMISSION_ID="$DMG_SUBMISSION_ID" \
APP_RECEIPT="$APP_RECEIPT" \
DMG_RECEIPT="$DMG_RECEIPT" \
  /usr/bin/python3 - <<'PY'
import json
import os

for path_key, id_key, target in (
    ("APP_RECEIPT", "APP_SUBMISSION_ID", "app"),
    ("DMG_RECEIPT", "DMG_SUBMISSION_ID", "dmg"),
):
    payload = {
        "schema_version": 1,
        "target": target,
        "submission_id": os.environ[id_key],
        "status": "Accepted",
    }
    with open(os.environ[path_key], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
PY

HEAD_SHA=$(/usr/bin/git -C "$ROOT" rev-parse HEAD)
APP_EXECUTABLE_SHA=$(/usr/bin/shasum -a 256 "$APP/Contents/MacOS/Project Brain" | /usr/bin/awk '{print $1}')
HELPER_SHA=$(/usr/bin/shasum -a 256 "$APP_HELPER" | /usr/bin/awk '{print $1}')
CLI_CONTRACT_SHA=$(/usr/bin/shasum -a 256 "$APP_CONTRACT" | /usr/bin/awk '{print $1}')
DMG_SHA=$(/usr/bin/shasum -a 256 "$DMG" | /usr/bin/awk '{print $1}')
ZIP_SHA=$(/usr/bin/shasum -a 256 "$APP_ZIP" | /usr/bin/awk '{print $1}')
APP_RECEIPT_SHA=$(/usr/bin/shasum -a 256 "$APP_RECEIPT" | /usr/bin/awk '{print $1}')
DMG_RECEIPT_SHA=$(/usr/bin/shasum -a 256 "$DMG_RECEIPT" | /usr/bin/awk '{print $1}')
MANIFEST="$STAGING_OUTPUT/build-manifest.json"

APP_VERSION="$APP_VERSION" \
APP_BUILD="$APP_BUILD" \
HEAD_SHA="$HEAD_SHA" \
APP_EXECUTABLE_SHA="$APP_EXECUTABLE_SHA" \
HELPER_SHA="$HELPER_SHA" \
CLI_CONTRACT_SHA="$CLI_CONTRACT_SHA" \
ARCHITECTURE="$ARCHITECTURE" \
CI_RUN_URL="$CI_RUN_URL" \
TEAM_ID="$TEAM_ID" \
SIGNING_IDENTITY="$SIGNING_IDENTITY" \
APP_SUBMISSION_ID="$APP_SUBMISSION_ID" \
DMG_SUBMISSION_ID="$DMG_SUBMISSION_ID" \
DMG_NAME=$(/usr/bin/basename "$DMG") \
DMG_SHA="$DMG_SHA" \
ZIP_NAME=$(/usr/bin/basename "$APP_ZIP") \
ZIP_SHA="$ZIP_SHA" \
APP_RECEIPT_NAME=$(/usr/bin/basename "$APP_RECEIPT") \
APP_RECEIPT_SHA="$APP_RECEIPT_SHA" \
DMG_RECEIPT_NAME=$(/usr/bin/basename "$DMG_RECEIPT") \
DMG_RECEIPT_SHA="$DMG_RECEIPT_SHA" \
OUTPUT_MANIFEST="$MANIFEST" \
  /usr/bin/python3 - <<'PY'
import json
import os

manifest = {
    "schema_version": 5,
    "artifact_classification": "developer_id_notarized_release_candidate",
    "distribution_eligible": False,
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
        "contract_version": "1.2.0",
        "core_version": "0.8.0",
        "document_sha256": os.environ["CLI_CONTRACT_SHA"],
    },
    "target_architecture": os.environ["ARCHITECTURE"],
    "signing": {
        "status": "developer_id_application_verified",
        "identity": os.environ["SIGNING_IDENTITY"],
        "team_id": os.environ["TEAM_ID"],
        "hardened_runtime": "enabled",
        "secure_timestamp": "verified",
        "get_task_allow": "absent",
    },
    "notarization": {
        "status": "accepted",
        "app_submission_id": os.environ["APP_SUBMISSION_ID"],
        "dmg_submission_id": os.environ["DMG_SUBMISSION_ID"],
        "app_ticket": "stapled_and_validated",
        "dmg_ticket": "stapled_and_validated",
    },
    "release_gate": {
        "developer_id_signature": "passed",
        "hardened_runtime": "passed",
        "secure_timestamp": "passed",
        "apple_notarization": "passed",
        "app_ticket_stapled": "passed",
        "dmg_ticket_stapled": "passed",
        "gatekeeper_assessment": "passed_ci",
        "fresh_mac_quarantine_acceptance": "pending_manual",
    },
    "ci_run_url": os.environ["CI_RUN_URL"],
    "external_acceptance": "pending_user_credentials_and_actions",
    "artifacts": [
        {"name": os.environ["DMG_NAME"], "sha256": os.environ["DMG_SHA"]},
        {"name": os.environ["ZIP_NAME"], "sha256": os.environ["ZIP_SHA"]},
        {
            "name": os.environ["APP_RECEIPT_NAME"],
            "sha256": os.environ["APP_RECEIPT_SHA"],
        },
        {
            "name": os.environ["DMG_RECEIPT_NAME"],
            "sha256": os.environ["DMG_RECEIPT_SHA"],
        },
    ],
}
with open(os.environ["OUTPUT_MANIFEST"], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

{
  /usr/bin/shasum -a 256 "$DMG"
  /usr/bin/shasum -a 256 "$APP_ZIP"
  /usr/bin/shasum -a 256 "$APP_RECEIPT"
  /usr/bin/shasum -a 256 "$DMG_RECEIPT"
  /usr/bin/shasum -a 256 "$MANIFEST"
} | /usr/bin/sed "s|$STAGING_OUTPUT/||" >"$STAGING_OUTPUT/SHA256SUMS"

/bin/mkdir -p "$(/usr/bin/dirname "$OUTPUT_DIR")"
/bin/mv "$STAGING_OUTPUT" "$OUTPUT_DIR"
echo "Build 10 notarized release candidate directory: $OUTPUT_DIR"
echo "Build 10 DMG SHA-256: $DMG_SHA"
echo "Fresh-Mac quarantine acceptance: pending manual"
echo "External ChatGPT acceptance: pending user credentials and actions"
