# Product Shell RC1 Build 6 installation hotfix verification

Base: `main@7a8275289ac949f418d60a7d20cca14a8ae728f9`

Version: `0.7.0 (6)`

Builds 4 and 5 are immutable release-candidate history. Build 6 supersedes
Build 5 for installation discoverability and application lifecycle behavior;
neither historical build may be deleted, rebuilt, or overwritten.

## Product gates

- The generated Release app sets the Boolean
  `LSMultipleInstancesProhibited` Launch Services key. The artifact build and
  mounted-DMG verifier inspect the final app `Info.plist`.
- The menu-bar panel and Settings both provide a visible **Quit Project Brain**
  action. Quit preserves all local Core and Tunnel state.
- The DMG root contains `Project Brain.app`, an `Applications` symlink targeting
  `/Applications`, and the bilingual visible guide
  `把 Project Brain.app 拖到 Applications 安装.txt`.
- The user copies the app, ejects the DMG, and launches only
  `/Applications/Project Brain.app` for formal acceptance.
- Existing onboarding identity, structured plan-time conflicts, transactional
  apply guards, inline recovery, and preserved-database behavior from Build 5
  remain unchanged.

## Artifact boundary

CI publishes the distinct artifact `Project-Brain-RC1-Build6-arm64`, containing
`Project-Brain-RC1-Build6-arm64.dmg`,
`Project-Brain-RC1-Build6-arm64.zip`, `build-manifest.json`, and `SHA256SUMS`.
The manifest binds the exact Git head, app `0.7.0 (6)`, Core helper SHA-256,
artifact SHA-256 values, and the GitHub Actions run URL.

The build remains an unsigned, unnotarized internal RC. Secure MCP Tunnel and
External ChatGPT acceptance remain Pending and cannot be closed by local or CI
transport tests.

## Verification boundary

The local Core/MCP suite passes 220 tests and both Swift app products compile.
This host has Apple Command Line Tools but not the XCTest module or full Xcode,
so SwiftPM/Xcode tests, Release packaging, mounted-DMG inspection, launchd, and
artifact hashes require the exact-head macOS GitHub Actions run. No result is
treated as complete until that workflow succeeds.
