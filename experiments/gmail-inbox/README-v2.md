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
