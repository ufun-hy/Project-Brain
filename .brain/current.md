# Current State

Last updated: 2026-07-18

## Current stage

Product Shell RC1 Build 6 installation-experience hotfix is implemented on the independent
`codex/project-brain-product-shell-hotfix-onboarding` branch from exact merged
base `main@7a8275289ac949f418d60a7d20cca14a8ae728f9`. The delivery target is Draft
PR #17. It must not be marked Ready or merged while external acceptance is
pending.

## Implemented Build 6 hotfix

- Project Brain 0.7.0 build 6 prohibits multiple instances through the macOS
  Launch Services bundle contract. Release packaging and mounted-DMG
  verification assert the emitted Boolean key in the final app bundle.
- The menu-bar panel and Settings each expose a direct Quit Project Brain
  action. Quit stops only the UI process and preserves projects, tasks,
  services, Keychain entries, and runtime data.
- The DMG includes an `/Applications` symlink beside the app and a visible
  bilingual drag-to-install guide. CI mounts the completed DMG and verifies the
  app, link target, guide, build number, and single-instance key.
- Build 6 uses distinct DMG/ZIP/workflow artifact names and manifest build
  metadata. Builds 4 and 5 remain immutable history and are superseded, not
  replaced.

## Preserved Build 5 onboarding hotfix

- Project Brain 0.7.0 build 5 resolves an onboarding repository against the
  preserved SQLite registrations using canonical real path, normalized origin,
  stable ID, and display name. Existing registrations produce `use_existing`
  or `update`, never a duplicate `add`.
- Project ID, name, and path conflicts are returned during planning with
  structured existing-project metadata and bounded recovery actions. Apply
  re-plans under RuntimeLock and SQLite keeps final transactional collision,
  revision, hash, and action checks.
- Onboarding errors render inside the active sheet with actions to use the
  existing project, select another directory, or edit the name.
- DMG and other non-Applications launches are explicitly not installed. Local
  readiness and onboarding completion require the exact
  `/Applications/Project Brain.app` bundle location.
- Build 5 uses distinct DMG/ZIP/workflow artifact names and manifest build
  metadata. Build 4 remains immutable history and is superseded, not replaced.

## Preserved RC1 implementation

- Project Brain schema v8 migration with stable
  installation identity, one-time transport-probe runs, append-only events, and
  safe downgrade of legacy v7 `passed` rows to unattributed evidence.
- A strict `project_brain_acceptance_probe` MCP tool. Core has no pass CLI and
  Swift has no pass command; MCP ingress records transport evidence only and
  never authenticates ChatGPT or marks external acceptance complete.
- 256-bit, ten-minute, hash-only, one-use challenges with mismatch, replay,
  concurrent-consumption, expiry, supersede, and restart recovery gates.
- The future fixed real-project acceptance task is locked until Core can supply
  applicable trusted ChatGPT control-plane attestation; unattributed current or
  historical transport evidence fails closed.
- Native Tunnel Client import with zero-execution static file/Mach-O/size/hash/
  quarantine/signing preflight, separate execution authorization, bundled
  schema-v1 compatibility manifest for 0.0.10 arm64, bounded fixed-argv version
  check, isolated read-only runtime-contract probe, atomic install, rollback,
  and fail-closed removal after confirmed stop.
- Connection Center transport-probe guidance with automatic waiting refresh,
  memory-only prompt, full current-binding applicability, explicit external
  Pending state, and a locked project-task preview.
- Redacted diagnostics with Tunnel fingerprint, not raw ID, and no challenge or
  credentials.
- CI Release DMG/ZIP, manifest, artifact hashes, unsigned/internal-RC labels,
  helper/resource checks, real launchd, SwiftPM/Xcode, and Gmail isolation.

## Preserved guarantees

- SQLite remains authoritative for task execution snapshots, canonical-head
  verification sets, review, recovery, forensics, and publication retry.
- All runtime subprocesses use absolute executable paths and typed fixed argv;
  no user command, shell, cwd, environment, SQL, or URL reaches execution.
- Runtime API keys remain Keychain-only. Tunnel Client is not committed or
  bundled, and the app never bypasses quarantine or Gatekeeper.
- Default checkouts and human changes are never reset or cleaned. Managed
  worktree cleanup retains existing forensic and ownership gates.
- No UI path accepts, merges, or manually marks external verification passed.
- Gmail legacy remains frozen and outside Product Shell.

## Verification status

Build 6 local and CI verification evidence is recorded in
`docs/product-shell-build6-installation-hotfix-verification.md`. The local
Core/MCP suite passes 220 tests and Swift app compilation passes. Exact-head
macOS CI remains required for XCTest, Xcode, launchd, Release packaging,
mounted-DMG layout, and artifact hashes. A CI probe remains transport evidence,
not external ChatGPT acceptance.

## External acceptance

Secure MCP Tunnel, real credentials, ChatGPT connector discovery, trusted
control-plane attestation, real-project Draft PR closure, Apple signing, and
notarization remain Pending. No local or CI result closes these gates.

## Read next

- `docs/product-shell.md`
- `docs/product-shell-build6-installation-hotfix-verification.md`
- `docs/product-shell-build5-hotfix-verification.md`
- `docs/product-shell-rc1-verification.md`
- `docs/rfc/RFC-007-zero-cli-rc1.md`
- `docs/mcp-adapter.md`
