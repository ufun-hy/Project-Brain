# Current State

Last updated: 2026-07-19

## Current stage

PR #17 / Build 7 was merged at exact base
`main@7259acfa1c38e30f3f8c2126eb7c7c3f8c271e3f`. RFC-008 local task intake is
implemented on the independent `codex/project-brain-local-task-intake-v1`
branch for Draft PR #18 and Project Brain 0.8.0 build 9. No historical PR or
artifact is reused.

## Local task intake

- Menu bar and Task Center expose review-first New Task actions; the empty
  state and one-time guided first run lead to the same sheet.
- Analyze/Review and Implement change use one schema-v1, source-neutral stdin
  JSON contract. Swift cannot supply command, argv, cwd, environment, SQL,
  paths, executables, branches, worktrees, credentials, or sandbox policy.
- SQLite schema v10 persists canonical local-task requests, exact request and
  plan hashes, execution
  snapshots, delivery, task type, and schema-v1 results while preserving old
  and external-source tasks.
- The transient `local-v2:` token is returned only to the App; SQLite stores its
  SHA-256. Confirmation contains only token and expected plan hash. RuntimeLock,
  remote Base, project revision/hash/path, delivery policy, readiness, expiry,
  transaction, and dedupe checks fail closed at confirmation.
- Analyze runs in a read-only isolated worktree, accepts no changes as normal
  success, records `completed`, and cannot commit, push, or create a PR.
- Implement retains the canonical commit, verification seal, bounded project
  push/Draft PR policy, review, retry, recovery, and worktree safety model.
- Task Center displays authoritative source/type/status/phase, execution
  snapshot, results, files, verification, publication, errors, recovery, and
  events. Menu counts update from the same Core observation stream.

## Packaging and verification

- App/Core are 0.8.0 with CLI contract 1.2.0, request/confirmation/result schema
  1, and database schema 10.
- English and Simplified Chinese strings are packaged by SwiftPM and Xcode.
- Build 9 uses distinct `Project-Brain-Local-Tasks-Build9-arm64` DMG/ZIP names
  and a schema-v4 manifest; Build 8 remains immutable history.
- Final-DMG CI mounts and installs the App, invokes the App/Core typed adapter in
  an isolated HOME, migrates a preserved schema-v9 database, creates and completes
  the reported exact-Chinese-goal Analyze task, restarts the App, records timing
  budgets, and proves the main checkout is
  unchanged. Implement worktree behavior is covered in Core integration tests;
  no unauthorized real GitHub PR is created.
- Local Python and Swift compilation must pass before push. SwiftPM XCTest,
  Xcode, real launchd, final DMG, and artifact hashes are authoritative on the
  exact-head macOS GitHub Actions run.

## Preserved guarantees

- The registered main checkout is never switched, reset, cleaned, or used as
  an agent working directory.
- Existing SQLite, projects, tasks, Keychain, Tunnel state, and user untracked
  files are not cleared, migrated outside schema rules, or altered for tests.
- Gmail legacy remains frozen and has zero tracked diff from the exact base.
- Core never merges automatically. Draft PR and review boundaries remain.

## External acceptance

Secure MCP Tunnel, real credentials, ChatGPT connector discovery and trusted
control-plane attribution remain **Pending**. Local task and artifact tests do
not satisfy or replace external ChatGPT acceptance. Signing, notarization, and
automatic updates are also outside RFC-008.

## Read next

- `docs/rfc/RFC-008-local-task-intake-and-guided-first-run-v1.md`
- `docs/product-shell.md`
- `docs/product-shell-build9-plan-confirm-verification.md`
- `docs/troubleshooting-recovery.md`
