# Current State

Last updated: 2026-07-17

## Current stage

Product Shell RC1 is implemented on the independent
`codex/project-brain-product-shell-rc1` branch stacked from exact Product Shell
v1 head `1475915a8c43681270c829ee96b4c4104659aa7a`. The delivery target is a new
Draft PR. It must not be marked Ready or merged while external acceptance is
pending.

## Implemented RC1

- Project Brain 0.7.0 build 3 and atomic schema v8 migration with stable
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

The full local Python/Core/MCP suite passes 204 tests, including a real direct
Streamable HTTP tool dispatch with spoofed source headers. Both ProjectBrainKit
and ProjectBrainApp compile through SwiftPM. This host has only Apple Command Line
Tools and no full Xcode/XCTest module, so SwiftPM XCTest, committed Xcode project
tests, Release app/DMG build, artifact upload, and launchd results must be taken
from the Draft PR macOS Actions run. A CI probe remains transport evidence, not
external ChatGPT acceptance.

## External acceptance

Secure MCP Tunnel, real credentials, ChatGPT connector discovery, trusted
control-plane attestation, real-project Draft PR closure, Apple signing, and
notarization remain Pending. No local or CI result closes these gates.

## Read next

- `docs/product-shell.md`
- `docs/product-shell-rc1-verification.md`
- `docs/rfc/RFC-007-zero-cli-rc1.md`
- `docs/mcp-adapter.md`
