#!/bin/sh
set -eu

DMG=${1:?usage: verify-rc-dmg-layout.sh /path/to/artifact.dmg}
MOUNT_ROOT=$(/usr/bin/mktemp -d "${RUNNER_TEMP:-/tmp}/project-brain-dmg-layout.XXXXXX")
MOUNT_POINT="$MOUNT_ROOT/mount"
ATTACHED=false

cleanup() {
  if [ "$ATTACHED" = true ]; then
    /usr/bin/hdiutil detach -quiet "$MOUNT_POINT" || true
  fi
  /bin/rm -rf "$MOUNT_ROOT"
}
trap cleanup EXIT INT TERM

/bin/mkdir -p "$MOUNT_POINT"
/usr/bin/hdiutil attach -quiet -readonly -nobrowse -mountpoint "$MOUNT_POINT" "$DMG"
ATTACHED=true

APP="$MOUNT_POINT/Project Brain.app"
GUIDE="$MOUNT_POINT/把 Project Brain.app 拖到 Applications 安装.txt"

test -d "$APP"
test -L "$MOUNT_POINT/Applications"
test "$(/usr/bin/readlink "$MOUNT_POINT/Applications")" = "/Applications"
test -f "$GUIDE"
/usr/bin/grep -Fq "拖到旁边的“Applications”文件夹" "$GUIDE"
test -x "$APP/Contents/Resources/project-brain"
test -f "$APP/Contents/Resources/project-brain-cli-contract.json"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")" = "8"
test "$(/usr/libexec/PlistBuddy -c 'Print :LSMultipleInstancesProhibited' "$APP/Contents/Info.plist")" = "true"

echo "Build 8 mounted DMG installation layout verification passed"
