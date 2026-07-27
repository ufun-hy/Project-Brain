#!/bin/sh
set -eu

DMG=${1:?usage: verify-notarized-gatekeeper.sh BUILD10_DMG}
if [ ! -f "$DMG" ]; then
  echo "error: Build 10 DMG does not exist" >&2
  exit 1
fi

TEMP_ROOT=$(/usr/bin/mktemp -d "${RUNNER_TEMP:-/tmp}/project-brain-gatekeeper.XXXXXX")
MOUNT_POINT="$TEMP_ROOT/mount"
QUARANTINED_DMG="$TEMP_ROOT/browser-download.dmg"
INSTALLED_APP="$TEMP_ROOT/Applications/Project Brain.app"
ATTACHED=0
cleanup() {
  if [ "$ATTACHED" -eq 1 ]; then
    /usr/bin/hdiutil detach "$MOUNT_POINT" -quiet || true
  fi
  /bin/rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT INT TERM

/usr/bin/codesign --verify --strict --verbose=2 "$DMG"
/usr/bin/xcrun stapler validate "$DMG"
/usr/sbin/spctl \
  --assess \
  --type open \
  --context context:primary-signature \
  --verbose=4 \
  "$DMG"

/usr/bin/ditto "$DMG" "$QUARANTINED_DMG"
/usr/bin/xattr -w \
  com.apple.quarantine \
  "0083;$(/bin/date +%s);ProjectBrainReleaseCI;https://github.com/ufun-hy/Project-Brain/" \
  "$QUARANTINED_DMG"
/usr/sbin/spctl \
  --assess \
  --type open \
  --context context:primary-signature \
  --verbose=4 \
  "$QUARANTINED_DMG"

/bin/mkdir -p "$MOUNT_POINT" "$TEMP_ROOT/Applications"
/usr/bin/hdiutil attach \
  -nobrowse \
  -readonly \
  -mountpoint "$MOUNT_POINT" \
  "$QUARANTINED_DMG" >/dev/null
ATTACHED=1
/usr/bin/ditto "$MOUNT_POINT/Project Brain.app" "$INSTALLED_APP"

if [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INSTALLED_APP/Contents/Info.plist")" != "0.8.0" ] ||
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INSTALLED_APP/Contents/Info.plist")" != "10" ]; then
  echo "error: mounted App version/build does not match Build 10" >&2
  exit 1
fi
/usr/bin/codesign --verify --deep --strict --verbose=2 "$INSTALLED_APP"
/usr/bin/codesign --verify --strict --verbose=2 \
  "$INSTALLED_APP/Contents/Resources/project-brain"
/usr/bin/xcrun stapler validate "$INSTALLED_APP"
/usr/sbin/spctl --assess --type execute --verbose=4 "$INSTALLED_APP"

echo "Build 10 signed, stapled, and Gatekeeper CI assessment passed"
echo "Fresh-Mac browser-download GUI acceptance remains pending manual validation"
