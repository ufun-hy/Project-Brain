# Project Brain Product Shell v1

## What the app provides

Project Brain is a native macOS 14 menu bar app with a management window. The
first-run flow installs the bundled Core helper, initializes the private local
runtime, validates and registers a Git repository through an explicit plan,
installs the Worker and MCP launchd services, and runs unified readiness checks.

After onboarding, the app provides:

- a primary **New Task…** action in the menu bar and Task Center, with a
  one-time guided first-task prompt after successful onboarding;
- review-first local task creation for read-only **Analyze / Review** and
  isolated-worktree **Implement change** tasks;
- a menu bar aggregate derived from durable Core task and service state;
- Task Center status, phase, attempt, branch/commit, Draft PR, changed files,
  verification criteria/evidence, review findings, errors, and next actions;
- project add/update plan and confirmation, intake pause/resume, and
  data-preserving soft removal;
- fixed Worker/MCP install, start, stop, restart, status, and uninstall actions;
- a controlled official `tunnel-client` adapter for zero-CLI
  import/install/replace/revalidate/remove, connect/status/stop/reconnect, and
  local/runtime readiness;
- an eleven-step external acceptance wizard backed by one-time Core challenges
  and a strict MCP ingress probe;
- an optional fixed, previewed real-project task that can change only
  `docs/project-brain-acceptance.md` and can publish only a Draft PR;
- automatic foreground/background task observation with selected-detail refresh
  and bounded failure/offline backoff;
- local health, service, task-recovery, and external-readiness diagnostics;
- a JSON diagnostic export that omits credentials, argv, runtime paths, repo
  paths, raw task payloads, and artifact contents.
- explicit Quit actions in the menu-bar panel and Settings. Quitting the app
  does not delete projects, tasks, services, or runtime data.

![First-run privacy and safety boundary](images/product-shell-onboarding.png)

## Build the unsigned development app

The repository never commits a frozen helper or `.app` binary. Build the
self-contained helper first, then give its absolute path to Xcode:

```bash
python3.11 -m venv /tmp/project-brain-build
/tmp/project-brain-build/bin/pip install -e '.[packaging]'
PROJECT_BRAIN_HELPER_DIST=/tmp/project-brain-helper-dist \
PROJECT_BRAIN_HELPER_WORK=/tmp/project-brain-helper-work \
PYTHON_BIN=/tmp/project-brain-build/bin/python \
scripts/build-macos-helper.sh

PROJECT_BRAIN_BUNDLED_HELPER=/tmp/project-brain-helper-dist/project-brain \
xcodebuild \
  -project apps/macos/ProjectBrain/ProjectBrain.xcodeproj \
  -scheme ProjectBrain \
  -destination 'platform=macOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

PyInstaller produces an architecture-specific `onefile` executable. The Xcode
post-build phase copies it into `Project Brain.app/Contents/Resources/` and
checks the executable bit. CI publishes an unsigned arm64 internal Build 9 DMG and
ZIP, build manifest, and SHA-256 values as a seven-day artifact. Signed,
notarized, universal distribution is a separate release task.

## Install the internal RC

1. Open the downloaded DMG.
2. Drag `Project Brain.app` onto the adjacent `Applications` folder icon. A
   bilingual installation guide is also visible in the DMG window.
3. Eject the DMG, then open `/Applications/Project Brain.app` from Finder's
   Applications folder. Do not run the copy inside the mounted DMG for formal
   acceptance.

The app combines the macOS single-instance Launch Services key with a user-level
non-blocking process lock, and uses one unique management `Window`. Starting the
DMG copy while the Applications copy is active wakes the existing instance and
exits; one process cannot create a second management window. Use **Quit Project
Brain** at the bottom of the menu-bar panel or in Settings to close it explicitly.

## First run

1. Read the local-data and Keychain privacy boundary.
2. Install the bundled helper and initialize `~/.project-brain/`.
3. Choose a Git repository using the native directory picker.
4. Review the detected project ID, configuration revision/hash, changed fields,
   immutable task-snapshot effect, and commit-bound plan token.
5. Confirm the plan. No project configuration is written before confirmation.
6. Install and start Worker and loopback-only MCP.
7. Run the unified readiness checks and finish onboarding. Readiness requires
   Core health, every project check, GitHub authentication, a healthy Worker,
   a running MCP service, and a successful MCP initialize handshake.

Onboarding progress is persisted and resumes from the last stage after an
interruption. Errors show a user-facing cause and next action; Python tracebacks
are not shown in the UI.

After onboarding, a single non-overlapping observation loop refreshes task and
service state every 3 seconds in the foreground and less often in the
background. Returning to the foreground triggers an immediate refresh. If a
task detail is open, that exact task is refreshed with the list. Failures use
exponential backoff and offline services use a slower interval.

## Create a local task

Use **New Task…** in the menu bar or **Create Task** in Task Center. Select a
registered project and choose:

- **Analyze / Review** for a read-only Codex pass. No code change is required;
  a structured result completes normally without commit, push, or PR.
- **Implement change** for an isolated task worktree. A canonical commit is
  required. Push and Draft PR can be disabled, but can never be enabled beyond
  the registered project execution policy.

Goal text must contain 10–8,000 Unicode characters. Acceptance criteria are
optional and limited to 8,000 characters total. They are transmitted as strict
schema-v1 JSON over stdin and are always treated as content: the App cannot
provide command, argv, cwd, environment, SQL, executable, branch, worktree,
credential, or sandbox controls.

**Review Execution Plan** shows project, task type, the full canonical goal,
file-modification and delivery effects, readiness, and primary risks. Repository
path, exact Base SHA, execution revision/hash, adapter, worktree root, expiry,
schema, and contract live in collapsed technical details. Only a short token
fingerprint is visible; the replayable token is never displayed.

Schema v10 stores the canonical request and plan hash but only the SHA-256 of
the transient `local-v2:` token. Confirmation sends exactly `plan_token` and
`expected_plan_hash` over stdin. Core rechecks the project, remote Base, policy,
readiness, expiry, supersession, and single-use state under RuntimeLock; task
creation and token consumption commit in one transaction. Expired, repeated,
hash-mismatched, superseded, and concurrent second confirmations fail closed.
After success the App closes the sheet from the minimal create response and
refreshes only the selected task in the background.

Task Center reads all list/detail/count state back from Core. It displays
source, task type, status, phase, execution snapshot, result, changed files,
verification, commit/branch/Draft PR, failure, recovery, and event timeline.
Closing or restarting the App does not lose the task or analysis result.

Local tasks require the managed Worker and registered project prerequisites.
They do not require ChatGPT, Secure MCP Tunnel, Gmail, or external acceptance.
External ChatGPT acceptance remains **Pending** even when a local task passes.

## Managed files and services

The installed helper is:

```text
~/Library/Application Support/Project Brain/bin/project-brain
```

The runtime remains:

```text
~/.project-brain/
```

The launchd labels are fixed:

```text
com.projectbrain.worker
com.projectbrain.mcp
```

Service uninstall removes the two private plists and unloads the services. It
does not remove the helper, database, task history, results, worktrees, project
repositories, or project registration. Product Shell v1 intentionally has no
runtime deletion action.

Loaded jobs are addressed by the single launchd service target
`gui/<uid>/<label>`. Only a confirmed not-loaded response is idempotent;
permission and other launchctl failures surface as service errors. Partial
install rolls back already activated jobs while retaining the generated private
plists for an explicit retry.

## Helper upgrade and recovery

The App and Core share packaged request/confirmation schema-v1 documents and
CLI contract version 1.2.0. The app validates the
bundled helper with fixed `--version` and `cli-contract --json` argv, and checks
the helper binary SHA-256 plus exact contract version/document SHA. A stale
same-version helper is therefore upgraded rather than retained. The candidate
is fsynced and atomically activated; the old executable remains available until
the new helper and service restart both succeed. A failed activation restores
and reactivates the previous helper.

## Connection acceptance

RC1 first asks the user to open the official OpenAI Platform Tunnels page and
select the downloaded client with the native file picker. The app rejects
links, directories, non-executables, unsupported Mach-O architectures, and
oversized files before executing any selected bytes. The first screen performs
only static file, Mach-O, SHA-256, quarantine, and code-signing inspection and
states that no official signing requirement or digest is pinned. Cancel is
zero-execution and zero-install. Only a separate execution authorization permits
fixed `--version` argv with bounded output and timeout; versions absent from the
bundled compatibility manifest are rejected.

The managed Tunnel Client is installed at:

```text
~/Library/Application Support/Project Brain/bin/tunnel-client
```

It is installed with private staging, fsync, atomic replacement, and upgrade
rollback. Before the rollback window closes, the candidate must pass the fixed
read-only `runtimes list --json` contract in an isolated temporary HOME. An
invalid command or JSON contract removes a fresh install or restores the prior
SHA on upgrade. The app never removes quarantine attributes. Binary removal
requires a confirmed stopped runtime and otherwise fails closed.

Connection Center discovers the official `tunnel-client` only from fixed system
locations and runs the official long-lived `runtimes connect/status/stop`
workflow with fixed arguments. The target is always
`http://127.0.0.1:7677/mcp`; tunnel IDs must match `tunnel_` plus 32 lowercase
hex characters. The Runtime API key is stored in Keychain and passed only as
`CONTROL_PLANE_API_KEY`, never as argv or profile content.

Removing a tunnel configuration is fail-closed. The app removes the Keychain
credential only after `tunnel-client` confirms that the runtime stopped or was
already stopped. A failed or malformed stop response leaves the credential and
stored connection state intact and presents a retryable error.

`ready_to_test` is derived, not manually assigned. It requires a valid tunnel
ID, a stored Runtime API key, a successful local MCP initialize handshake, and
a tunnel status reporting `process_running`, `healthy`, and `ready`. An
operator can separately declare that ChatGPT workspace configuration is
prepared, but this never becomes `externally_verified`.

The app creates a 256-bit, ten-minute, one-time transport challenge and keeps
its plaintext only in memory. Core schema v8 persists only its SHA-256 and
binds the run to app/Core version, installation identity, Tunnel fingerprint,
acceptance contract, and timestamps. A call to
`project_brain_acceptance_probe` writes `mcp_transport_probe_passed` with source
`local_or_tunneled_mcp_unattributed`; a local direct client can perform the same
call, so it never writes `external_chatgpt_verified`. App restart restores the
Core run but cannot restore challenge plaintext. Historical transport evidence
is compared with the current installation/app/Core/Tunnel/contract set and is
displayed separately from current applicability. External ChatGPT acceptance
remains Pending because trusted control-plane attestation is unavailable.

The fixed real-project acceptance task remains fail-closed until Core can supply
an applicable trusted ChatGPT control-plane attestation. Historical or currently
applicable unattributed transport probes do not unlock it. The app cannot merge.

Project add/update apply operations submit the exact plan token shown in the
UI. Core recomputes it under the runtime lock and verifies the expected current
revision/hash/name, next hash/name, and action again inside the write
transaction. A concurrent change returns `state_conflict` and requires a fresh
plan.

Local task failures remain in the current task sheet. A stale plan offers
**Review new plan**; failed readiness offers **Open Diagnostics**. The App does
not show argparse usage or Python tracebacks. Interrupted execution continues
to use the common process identity, recovery-block, retry-limit, forensic, and
safe worktree cleanup rules.

These remain pending and cannot be replaced by local mocks:

- OpenAI Secure MCP Tunnel acceptance;
- ChatGPT developer-mode acceptance;
- a real project task → verification → Draft PR → needs_changes → retry →
  succeeded lifecycle observed in Product Shell.

## Troubleshooting

- **Helper needs repair:** use Settings → Reinstall or upgrade bundled helper.
- **Worker/MCP stopped:** use Connection Center → Start or Restart.
- **Project plan rejected:** validate the chosen directory is a Git repository
  with an origin, and select an absolute executable Codex installation.
- **Task recovery blocked:** inspect Diagnostics and task evidence. The app does
  not expose blind worktree cleanup or process termination.
- **Local plan changed or expired:** return to the task form, select **Review
  new plan**, and confirm the newly displayed Base/profile/readiness snapshot.
- **Analyze produced no files:** this is expected; inspect the structured
  analysis result in Task Center. It is not an implementation failure.
- **External connection pending:** finish tunnel and ChatGPT configuration, then
  execute the real acceptance flow; local MCP health is not external success.

Technical decisions and threat boundaries are in
[`rfc/RFC-006-product-shell-v1.md`](rfc/RFC-006-product-shell-v1.md) and
[`rfc/RFC-007-zero-cli-rc1.md`](rfc/RFC-007-zero-cli-rc1.md).
Local task behavior and acceptance constraints are in
[`rfc/RFC-008-local-task-intake-and-guided-first-run-v1.md`](rfc/RFC-008-local-task-intake-and-guided-first-run-v1.md).
