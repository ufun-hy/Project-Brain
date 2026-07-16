# RFC-006: Project Brain Product Shell v1

Status: Implementing
Platform: macOS 14+
Repository acceptance: pending
Secure MCP Tunnel / ChatGPT acceptance: pending external productized test

## Decision

Project Brain v1 ships as a native SwiftUI menu bar application with a management
window. The application is the normal user entrypoint. The Python CLI remains a
fixed, internal JSON adapter and diagnostic surface; the UI never opens a shell or
accepts arbitrary argv, cwd, environment, SQL, Git cleanup, review acceptance, or
merge instructions.

The product is split into four independently reviewable layers:

1. Core-owned launchd service lifecycle and project intake lifecycle.
2. A self-contained PyInstaller helper plus an atomic App-to-Application-Support
   installer with rollback.
3. A native SwiftUI shell for onboarding, tasks, projects, services, connections,
   diagnostics, and settings.
4. Fixture integration, Linux/macOS CI, operational documentation, and evidence.

The existing Core state machine, immutable task execution snapshots, verification
sets, canonical-head review binding, worktree safety, and Draft PR behavior remain
authoritative.

## Runtime and installation boundaries

Mutable Core state remains at `~/.project-brain/`. Product Shell v1 does not move,
copy, or silently migrate that runtime.

The bundled helper is installed at:

```text
~/Library/Application Support/Project Brain/bin/project-brain
```

The App copies a candidate to the destination filesystem, makes it executable,
executes only `<candidate> --version`, and atomically replaces the installed helper.
The previous executable is retained as rollback state until the replacement passes
validation. Upgrade failure restores the previously runnable helper.

The helper is built as a PyInstaller `onefile` executable. This avoids requiring
Python or a user-created virtual environment and matches the single-file atomic
upgrade protocol. It incurs a small extraction cost at process startup and is
architecture-specific. v1 CI produces an Apple Silicon artifact; universal and
signed/notarized distribution remains a release-engineering follow-up.

Large generated helper bundles and app archives are CI artifacts and are not
committed.

## Fixed helper protocol

Swift invokes an absolute helper URL with `Process.executableURL` and an allowlisted
argument array. It never invokes `/bin/sh`, `/bin/zsh`, `-c`, or concatenated
commands. stdout must decode as exactly one JSON value. stderr is bounded and
redacted before presentation or export.

The initial allowlist is:

- `init --json`
- `status --json`
- `health --json`
- `projects list/add/update/pause/resume/remove`
- `tasks list/show`
- `service plan/install/start/stop/restart/status/uninstall`

The UI supplies only typed values at documented positions. It does not expose a
generic command runner.

## Project lifecycle

Schema v6 adds two operational flags that are deliberately excluded from execution
profile hashes:

- `accepting_tasks`: false rejects new canonical task intake but does not cancel or
  rewrite an already accepted task.
- `registered`: false hides the project from active product views while preserving
  its row, tasks, snapshots, events, verification evidence, and forensic history.

Soft removal is refused while nonterminal tasks exist. Re-registering the same
project ID restores intake without changing old task snapshots.

All project changes expose a plan first. The App asks for confirmation and only
then invokes the corresponding explicit execute operation.

## launchd services

Product Shell manages exactly two per-user services:

| Service | Label | Behavior |
| --- | --- | --- |
| Worker | `com.projectbrain.worker` | `apply --json`, one task per process, every 30 seconds |
| MCP | `com.projectbrain.mcp` | long-running loopback `127.0.0.1:7677` Streamable HTTP |

`ProgramArguments` contains an absolute helper path and fixed arguments. No shell
wrapper is permitted. Plists are generated with `plistlib`, written through a
private fsynced temporary file, atomically replaced at mode `0600`, and loaded into
the current `gui/<uid>` domain. Logs remain under `~/.project-brain/logs/`.

`service plan` is read-only. Install/reinstall, start, stop, restart, and uninstall
are idempotent. Uninstall removes only the two owned plists and launchd jobs; it
does not remove the database, results, task history, registered repositories, or
runtime root. Runtime deletion is not exposed in v1.

Status is one of `not_installed`, `stopped`, `healthy`, or `unhealthy`, derived from
plist presence and `launchctl print`. Process presence never implies task success.

## Product information architecture

`Project Brain.app` provides:

- a menu bar aggregate: Healthy, Running, Needs attention, or Offline;
- a resumable first-run flow for privacy, runtime, first project, plan confirmation,
  helper/service installation, local health, and external acceptance pending;
- a task center showing state, phase, attempt, elapsed time, bounded path/branch
  summaries, verification evidence, review findings, commit, Draft PR, error, and
  next action;
- project management with native directory selection, trusted verification input,
  configuration revision/hash summary, pause/resume, and soft removal;
- a connection center that distinguishes local MCP health, tunnel configuration,
  ChatGPT workspace readiness, and external acceptance state;
- diagnostics with severity, task-blocking impact, deterministic low-risk repair,
  operator guidance, and redacted export;
- settings for helper repair, fixed service lifecycle, onboarding, and safety
  boundaries.

The UI never marks Tunnel, ChatGPT developer mode, or real-project acceptance as
passed from local checks. Those states begin at `not_started` or `ready_to_test`
and require the deferred external workflow.

## Secrets and diagnostics

Tunnel tokens and similar secrets use macOS Keychain. They are never written to
SQLite, UserDefaults, launchd plists, logs, events, PRs, or diagnostics. UserDefaults
may store only non-secret onboarding and external acceptance metadata.

Diagnostic export uses typed safe models. Raw task payloads, execution profiles,
argv, environments, local absolute paths, artifact contents, and Keychain values
are excluded. The report is written privately and does not execute checks that
mutate repositories or runtime state.

## Failure and rollback

- Helper validation failure leaves the installed helper unchanged.
- Post-replacement validation failure restores the prior helper.
- Partial service installation is safe to retry; every operation regenerates the
  same two plists and uses fixed labels.
- Service uninstall leaves all runtime data in place.
- A missing/invalid helper, schema mismatch, held runtime lock, unhealthy service,
  invalid project repository, or unsafe Codex executable is visible as a blocking
  diagnostic with a bounded next action.
- No operation resets, checks out, cleans, or deletes a user project checkout.

## Verification

Repository acceptance requires all existing Core/MCP tests plus:

- Python service plan, fixed plist, idempotence, lifecycle status, preservation,
  schema v6, project pause, and soft-removal tests;
- helper bundle, version, install, upgrade, and rollback tests;
- Swift decoding, status aggregation, onboarding recovery, project confirmation,
  error presentation, fixed argv, Keychain/log redaction, and helper installer tests;
- fixture-runtime service integration without real Codex, PR creation, Tunnel token,
  or user repositories;
- Linux Core CI and macOS helper/App build plus Swift tests;
- zero tracked diff under `experiments/gmail-inbox/` relative to the task base.

The repository PR remains Draft after these gates. Secure MCP Tunnel, ChatGPT
developer mode, and a real project lifecycle remain explicitly pending until the
user runs the productized end-to-end acceptance flow.

## Non-goals

v1 does not provide Windows/Linux GUI, cloud hosting, accounts, organizations,
billing, a public unauthenticated MCP endpoint, arbitrary command execution,
automatic review acceptance, automatic merge, runtime-root migration, or Gmail
productization. The untracked legacy menu bar experiment is not copied, imported,
modified, or used as an implementation source.
