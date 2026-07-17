#!/bin/sh
set -eu

ROOT=$(/usr/bin/git rev-parse --show-toplevel)
PROJECT="$ROOT/apps/macos/ProjectBrain/ProjectBrain.xcodeproj"
OUTPUT_DIR=${PROJECT_BRAIN_RC_OUTPUT_DIR:?PROJECT_BRAIN_RC_OUTPUT_DIR is required}
DERIVED_DATA=${PROJECT_BRAIN_RC_DERIVED_DATA:?PROJECT_BRAIN_RC_DERIVED_DATA is required}
HELPER=${PROJECT_BRAIN_BUNDLED_HELPER:?PROJECT_BRAIN_BUNDLED_HELPER is required}
CI_RUN_URL=${PROJECT_BRAIN_CI_RUN_URL:-local_unpublished_build}
APP_VERSION=0.7.0
APP_BUILD=1
ARCHITECTURE=arm64
ARTIFACT_BASE=Project-Brain-RC1-arm64

if [ ! -x "$HELPER" ]; then
  echo "error: self-contained Core helper is missing or not executable" >&2
  exit 1
fi
if [ "$("$HELPER" --version)" != "project-brain 0.7.0" ]; then
  echo "error: self-contained Core helper version does not match RC1" >&2
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
if [ ! -f "$APP/Contents/Resources/tunnel-client-compatibility.json" ]; then
  echo "error: Release app does not contain the static Tunnel compatibility manifest" >&2
  exit 1
fi
if [ -e "$APP/Contents/Resources/tunnel-client" ]; then
  echo "error: Tunnel Client must not be bundled in Project Brain.app" >&2
  exit 1
fi

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

DMG="$OUTPUT_DIR/$ARTIFACT_BASE.dmg"
ZIP="$OUTPUT_DIR/$ARTIFACT_BASE.zip"
/usr/bin/hdiutil create \
  -quiet \
  -volname "Project Brain RC1" \
  -srcfolder "$TEMP_ROOT/dmg" \
  -format UDZO \
  -ov \
  "$DMG"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

HEAD_SHA=$(/usr/bin/git -C "$ROOT" rev-parse HEAD)
HELPER_SHA=$(/usr/bin/shasum -a 256 "$HELPER" | /usr/bin/awk '{print $1}')
DMG_SHA=$(/usr/bin/shasum -a 256 "$DMG" | /usr/bin/awk '{print $1}')
ZIP_SHA=$(/usr/bin/shasum -a 256 "$ZIP" | /usr/bin/awk '{print $1}')
MANIFEST="$OUTPUT_DIR/build-manifest.json"

APP_VERSION="$APP_VERSION" \
APP_BUILD="$APP_BUILD" \
HEAD_SHA="$HEAD_SHA" \
HELPER_SHA="$HELPER_SHA" \
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
    "schema_version": 1,
    "artifact_classification": "unsigned_internal_rc",
    "app": {
        "version": os.environ["APP_VERSION"],
        "build": os.environ["APP_BUILD"],
    },
    "git_head_sha": os.environ["HEAD_SHA"],
    "core_helper": {
        "version": "0.7.0",
        "sha256": os.environ["HELPER_SHA"],
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

echo "RC1 artifact directory: $OUTPUT_DIR"
echo "RC1 DMG SHA-256: $DMG_SHA"
echo "RC1 classification: unsigned_internal_rc; not notarized"
echo "External acceptance: pending; this build did not use real ChatGPT ingress"
