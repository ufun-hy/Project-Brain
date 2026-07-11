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

### Push and PR

When `auto_push` and `auto_pr` are true, the bridge pushes the task branch and
opens a Draft PR through GitHub CLI.
