# Project Brain Bridge v2

This version completes the end-to-end workflow:

```text
ChatGPT -> Gmail -> local Bridge -> Git branch
-> write/Codex/allowlisted command -> commit -> push -> Draft PR
```

## What is intentionally not allowed

The following are not implemented as unrestricted operations:

- arbitrary shell from email
- unregistered repositories
- direct writes to `main` or `master`

These are security boundaries, not missing features.

## Requirements

Already required by the v0 Gmail experiment:

- `credentials.json`
- `token.json`
- `.venv`

Additional local tools:

```bash
git --version
gh --version
codex --version
```

Authenticate GitHub CLI once:

```bash
gh auth login
gh auth status
```

## Install

Copy these files into the existing directory:

```text
experiments/gmail-inbox/
```

Then:

```bash
chmod +x run_v2.sh
cp bridge-config.v2.example.json bridge-config.json
```

Edit the repository path in `bridge-config.json`.

Local-only files that should remain ignored:

```text
credentials.json
token.json
bridge-config.json
processed.json
failures.json
results/
.venv/
```

## Dry run

```bash
./run_v2.sh dry-run
```

## Execute once

```bash
./run_v2.sh apply
```

## Continuous polling

```bash
./run_v2.sh daemon
```

The daemon checks Gmail once per minute.

## Task formats

Email subject must start with:

```text
[Project Brain]
```

Email body must be valid JSON.

See:

- `task-write-files.json`
- `task-codex.json`
- `task-command.json`

## Safety model

## Task status and audit

The versioned schema is `task-status.schema.json`. Live records, bounded log tails,
logs, and durable execution reports are written atomically below
`~/Library/Application Support/ProjectBrain/` by default. Override both Bridge,
CLI, and menu app with `PROJECT_BRAIN_RUNTIME_DIR`. This location is runtime data
and must never be committed.

Lifecycle: `queued -> claimed -> running -> awaiting_review -> accepted | needs_changes`.
Exceptional terminal states are `blocked`, `failed`, and `cancelled`. A successful
process or test means only `awaiting_review`; it can never imply acceptance.

Inspect the same records used by the menu app:

```bash
python status_cli.py list
python status_cli.py show MESSAGE_ID
python status_cli.py review MESSAGE_ID accepted --reason "Reviewed PR and evidence"
python status_cli.py review MESSAGE_ID needs_changes --reason "Test gap remains"
```

Running records whose heartbeat is older than 180 seconds display as stale. Inspect
the log and repository, then record a deliberate recovery/review action; the Bridge
does not silently reinterpret stale work as successful.

## Native menu bar app

Requires macOS 13+ and a matching Xcode/Command Line Tools installation:

```bash
cd MenuBar
swift test
swift build -c release
swift run ProjectBrainMenuBar
```

The app polls the local task records, shows idle/running/review/error icon states,
task timing, heartbeat/stale state, acceptance counts, tests, PR and log actions.
It notifies only on running (started), awaiting review, blocked, failed, accepted,
and needs changes. No binary or `.build` output is committed.

## Gmail callbacks and OAuth

Only `awaiting_review`, `blocked`, and `failed` produce a thread reply; heartbeats
never send mail. Sending is behind `GmailCallback`, with `FakeCallback` in tests.
Bridge v2 now requests `gmail.modify`. Existing read-only tokens cannot send: delete
only the ignored local `token.json`, run `./run_v2.sh dry-run`, and approve the new
scope once. Credentials and tokens remain local and ignored.

### Registered projects only

Every repository must exist in `bridge-config.json`.

### Protected base branch

Tasks always branch from `main` or `master`. The bridge never commits directly
to a protected branch.

### Named commands only

A command email contains a name such as `test`; the actual command line is
defined locally in `allowed_commands`.

### Duplicate protection

After a successful apply, the Gmail message ID is added to `processed.json`.

Failures are recorded separately in `failures.json` with the attempt count,
last error, and timestamp. The bridge retries at most `max_attempts` times
(default: 3), then reports `retry_limit_reached` without invoking Codex again.
After fixing the underlying problem, remove only that message ID from
`failures.json` to allow a deliberate retry.

### Branch cleanup and recovery

After a successful push and Draft PR, the bridge checks out the configured base
branch and verifies that the worktree is clean; the pushed PR branch is kept.
On task failure it discards only changes made on the deterministic task branch,
returns to the base branch, and removes that local task branch. The preflight
clean-worktree check prevents overwriting existing user work.

If a task branch already exists, the bridge removes it only when it is an
unchanged, unpushed stale branch. A pushed branch or a local branch containing
commits stops with an actionable error. Inspect its PR/commits and resolve it
manually; the bridge never force-deletes a remote PR branch.

### Push and PR

When `auto_push` and `auto_pr` are true, the bridge pushes the task branch and
opens a Draft PR through GitHub CLI.
