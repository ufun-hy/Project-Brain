# Project Brain Product Shell v1

## What the app provides

Project Brain is a native macOS 14 menu bar app with a management window. The
first-run flow installs the bundled Core helper, initializes the private local
runtime, validates and registers a Git repository through an explicit plan,
installs the Worker and MCP launchd services, and runs local health checks.

After onboarding, the app provides:

- a menu bar aggregate derived from durable Core task and service state;
- Task Center status, phase, attempt, branch/commit, Draft PR, changed files,
  verification criteria/evidence, review findings, errors, and next actions;
- project add/update plan and confirmation, intake pause/resume, and
  data-preserving soft removal;
- fixed Worker/MCP install, start, stop, restart, status, and uninstall actions;
- Keychain-backed Secure MCP Tunnel token preparation;
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
checks the executable bit. CI publishes the unsigned app as a short-lived build
artifact; signed, notarized, universal distribution is a separate release task.

## First run

1. Read the local-data and Keychain privacy boundary.
2. Install the bundled helper and initialize `~/.project-brain/`.
3. Choose a Git repository using the native directory picker.
4. Review the detected project ID, configuration revision/hash, changed fields,
   and immutable task-snapshot effect.
5. Confirm the plan. No project configuration is written before confirmation.
6. Install and start Worker and loopback-only MCP.
7. Run local health checks and finish onboarding.

Onboarding progress is persisted and resumes from the last stage after an
interruption. Errors show a user-facing cause and next action; Python tracebacks
are not shown in the UI.

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

## Helper upgrade and recovery

The app validates the bundled helper with the fixed `--version` argv, copies it
to a private candidate file, validates its executable bit and version, fsyncs
it, and atomically replaces the managed helper. During upgrades it retains the
old executable until the new helper and service restart both succeed. A failed
activation restores and reactivates the previous helper.

## Connection acceptance

Connection Center can store a tunnel token only in macOS Keychain and mark the
workspace configuration as prepared. Before a real external flow, the product
shows only `not_started` or `ready_to_test`.

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
[`rfc/RFC-006-product-shell-v1.md`](rfc/RFC-006-product-shell-v1.md).
