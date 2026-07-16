# Current State

Last updated: 2026-07-16

## Current stage

PR #13 (controlled MCP Adapter) and PR #14 (project onboarding/config
snapshots) are merged into `main`. Product Shell v1 is implemented on the
independent `codex/project-brain-product-shell-v1` branch from base
`7dcf1f8c59937d2195ae75404ab7b4e4801c5c31`. It is intended for a new Draft PR
and must not be marked Ready or merged during repository acceptance.

## Implemented Product Shell

- Native macOS 14 SwiftUI menu bar app and management window under
  `apps/macos/ProjectBrain/`.
- Seven-step persisted onboarding: privacy, helper/runtime, project selection,
  plan confirmation, Worker/MCP install, health, and external-pending handoff.
- Typed fixed-argv Core adapter, durable task/evidence presentation, project
  lifecycle/config management with transaction-bound plan tokens, launchd
  service control, a controlled official Tunnel runtime adapter, automatic
  state observation, unified product readiness, and redacted diagnostics.
- PyInstaller onefile Core helper with exact version validation and atomic
  install/upgrade/rollback. Failed service activation restores and reactivates
  the previously runnable helper.
- Schema v6 project intake pause/resume and history-preserving soft removal.
- Linux Python, macOS helper/Swift/app, fixture lifecycle, and Gmail isolation
  CI gates.

## Preserved guarantees

- SQLite remains authoritative; task execution snapshots, canonical-head
  verification sets, review lifecycle, recovery, forensics, and worktree safety
  are unchanged.
- UI exposes no arbitrary shell, argv, cwd, environment, SQL, merge, acceptance,
  runtime deletion, or blind cleanup controls.
- Worker and MCP use fixed launchd labels and absolute helper argv. MCP remains
  loopback-only.
- Stop/uninstall address launchd jobs by exact `gui/<uid>/<label>` targets;
  partial activation is rolled back and exercised by a real macOS CI lifecycle.
- Onboarding Ready requires GitHub auth, all project checks, Worker/MCP state,
  and a real MCP initialize handshake.
- Tunnel `ready_to_test` is derived from local transport plus official runtime
  `process_running`/`healthy`/`ready`; operator declaration is not external
  verification.
- Credentials enter macOS Keychain, not SQLite, plist, logs, tasks, diagnostics,
  or PR data.
- Service uninstall preserves the runtime, project repositories, registration,
  and task history.
- Gmail legacy remains frozen and excluded from Product Shell.

## Verification status

Local Python/Core/MCP and fixture integration tests pass (186 tests). The SwiftUI executable
and ProjectBrainKit compile locally. The host does not contain full Xcode, so
the 25 XCTest cases and `Project Brain.app` build acceptance remain pending until the Draft
PR macOS GitHub Actions job is green. Exact counts, SHAs, URLs, and isolation
evidence are recorded at delivery.

## External acceptance

Secure MCP Tunnel, ChatGPT developer-mode, and real-project Product Shell
acceptance remain pending. Local tests and local MCP health do not replace them.

## Read next

- `docs/product-shell.md`
- `docs/product-shell-verification.md`
- `docs/rfc/RFC-006-product-shell-v1.md`
- `docs/project-configuration.md`
- `docs/mcp-adapter.md`
