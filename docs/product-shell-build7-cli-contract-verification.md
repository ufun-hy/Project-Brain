# Product Shell RC1 Build 7 CLI contract verification

Base: `main@7a8275289ac949f418d60a7d20cca14a8ae728f9`

Version: `0.7.0 (7)`

Build 6 is immutable release-candidate history. Build 7 supersedes it for
formal onboarding acceptance; the Build 6 artifact is not deleted, rebuilt, or
overwritten.

## F8 closure gates

- Python owns a packaged schema-v1, contract-version `1.0.0` CLI document. The
  App builds native onboarding argv from that document, including
  `--resolve-existing`; Core exposes the exact same document and SHA through
  `cli-contract --json` without initializing or modifying a runtime.
- Helper installation requires semantic version, binary SHA-256, contract
  content, and contract document SHA to match the App. A stale `0.7.0` managed
  helper is atomically upgraded even though its semantic version matches.
- The final Release `.app` contract resource and embedded helper are compared
  to the canonical repository document. The final embedded helper creates an
  isolated project, then plans and applies repeat onboarding as
  `use_existing`; its database and project list must remain byte-for-byte and
  structurally unchanged.
- The app uses a user-level process lock in addition to
  `LSMultipleInstancesProhibited`, and a unique SwiftUI management `Window` in
  place of `WindowGroup`. Isolated CI launches the final `/Applications` copy
  and mounted-DMG copy and requires exactly one process and one visible
  management window.

## Artifact boundary

CI publishes only the distinct `Project-Brain-RC1-Build7-arm64` artifact. Its
schema-v2 manifest binds the exact Git head, App version/build and executable
SHA-256, Core helper version/SHA-256, CLI schema/contract/Core versions and
document SHA-256, DMG/ZIP hashes, and GitHub Actions run URL.

The artifact remains unsigned and unnotarized. External ChatGPT acceptance is
`pending_user_credentials_and_actions`; local transport, contract, onboarding,
and single-instance tests cannot change that authority.
