# Project Brain Product Shell v1

## What the app provides

Project Brain is a native macOS 14 menu bar app with a management window. The
first-run flow installs the bundled Core helper, initializes the private local
runtime, validates and registers a Git repository through an explicit plan,
installs the Worker and MCP launchd services, and runs unified readiness checks.

After onboarding, the app provides:

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
checks the executable bit. CI publishes an unsigned arm64 internal RC1 DMG and
ZIP, build manifest, and SHA-256 values as a seven-day artifact. Signed,
notarized, universal distribution is a separate release task.

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

The app validates the bundled helper with the fixed `--version` argv, copies it
to a private candidate file, validates its executable bit and version, fsyncs
it, and atomically replaces the managed helper. During upgrades it retains the
old executable until the new helper and service restart both succeed. A failed
activation restores and reactivates the previous helper.

## Connection acceptance

RC1 first asks the user to open the official OpenAI Platform Tunnels page and
select the downloaded client with the native file picker. The app rejects
links, directories, non-executables, unsupported Mach-O architectures, and
versions absent from the bundled compatibility manifest. Version checks use
only fixed `--version` argv with bounded output and timeout. The confirmation
screen shows SHA-256 and explicitly says that official origin is confirmed by
the user when no machine-verifiable upstream digest is available.

The managed Tunnel Client is installed at:

```text
~/Library/Application Support/Project Brain/bin/tunnel-client
```

It is installed with private staging, fsync, atomic replacement, and upgrade
rollback. The app never removes quarantine attributes. Binary removal requires
a confirmed stopped runtime and otherwise fails closed.

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
prepared, but this never becomes `externally_verified`. Only the deferred real
ChatGPT flow can produce external success.

The app creates a 256-bit, ten-minute, one-time acceptance challenge and keeps
its plaintext only in memory. Core schema v7 persists only its SHA-256 and
binds the run to app/Core version, installation identity, Tunnel fingerprint,
and timestamps. The prompt is copied into ChatGPT; only a real dispatch of
`project_brain_acceptance_probe` through MCP can write `passed`. App restart
restores the Core run but cannot restore challenge plaintext. Historical pass
and current Tunnel health are displayed separately.

After a historical pass, the user may choose an eligible registered project,
review a plan-token-bound preview, and create the fixed acceptance document
task. The existing isolated worktree, Codex, verification-set, push, and Draft
PR pipeline remains authoritative; the app cannot merge.

Project add/update apply operations submit the exact plan token shown in the
UI. Core recomputes it under the runtime lock and verifies the expected current
revision/hash/name, next hash/name, and action again inside the write
transaction. A concurrent change returns `state_conflict` and requires a fresh
plan.

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
- **External connection pending:** finish tunnel and ChatGPT configuration, then
  execute the real acceptance flow; local MCP health is not external success.

Technical decisions and threat boundaries are in
[`rfc/RFC-006-product-shell-v1.md`](rfc/RFC-006-product-shell-v1.md) and
[`rfc/RFC-007-zero-cli-rc1.md`](rfc/RFC-007-zero-cli-rc1.md).
