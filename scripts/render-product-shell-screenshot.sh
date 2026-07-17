#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="$ROOT/apps/macos/ProjectBrain"
OUTPUT="${1:-$ROOT/docs/images/product-shell-onboarding.png}"
BIN_PATH="$(swift build --package-path "$PACKAGE" --show-bin-path)"
RENDERER="${TMPDIR:-/tmp}/project-brain-screenshot-renderer"

swift build --package-path "$PACKAGE" --target ProjectBrainKit
swiftc \
  -parse-as-library \
  -I "$BIN_PATH/Modules" \
  "$PACKAGE/ProjectBrain/AppModel.swift" \
  "$PACKAGE/ProjectBrain/OnboardingView.swift" \
  "$ROOT/scripts/render-product-shell-screenshot.swift" \
  "$BIN_PATH"/ProjectBrainKit.build/*.swift.o \
  -framework AppKit \
  -framework Combine \
  -framework Security \
  -framework SwiftUI \
  -o "$RENDERER"
"$RENDERER" "$OUTPUT"
echo "screenshot_path=$OUTPUT"
