# Project Brain Core MVP

Project Brain is a local project control layer between users, planning tools,
coding agents, and GitHub review. Core owns durable task state and safe local
execution. Gmail is retained as a compatibility input, not as the task engine.

## Core guarantees

- Stable project and task identities are persisted in SQLite.
- Every task runs in its own registered Git worktree.
- The registered main checkout is never checked out, reset, cleaned, or used as
  the Codex working directory.
- One runtime lock is shared by manual and scheduled runs.
- One apply process claims at most one task and exits.
- Codex commits and ordinary cherry-picks are normalized into a canonical
  per-attempt commit; unsafe history and branch changes stop the task.
- Execution success enters `awaiting_review`, never `accepted`.
- Acceptance criteria keep independent evidence records.
- GitHub publishing creates Draft PRs only; Core does not merge them.

Architecture and decisions are documented in
[`docs/rfc/RFC-003-core-v3.md`](docs/rfc/RFC-003-core-v3.md). The baseline gap
analysis is in [`docs/core-v3-gap-analysis.md`](docs/core-v3-gap-analysis.md).

## Requirements

- Python 3.10+
- Git
- GitHub CLI (`gh`) when `auto_push`/`auto_pr` is enabled
- Codex CLI, or another explicitly configured local agent command
- Gmail Python dependencies only when the Gmail adapter is used

## Install

Create a dedicated environment outside the source checkout when possible:

```bash
python3.11 -m venv ~/.project-brain/app/venv
~/.project-brain/app/venv/bin/pip install -e .
```

The installed command is `project-brain`. From a source checkout, the equivalent
is:

```bash
PYTHONPATH=src python -m project_brain --help
```

For Gmail support:

```bash
~/.project-brain/app/venv/bin/pip install -r experiments/gmail-inbox/requirements.txt
```

## Runtime layout

Mutable state defaults to `~/.project-brain/`:

```text
~/.project-brain/
├── config/
│   ├── bridge-config.json
│   ├── credentials.json       # optional Gmail OAuth client; never commit
│   └── token.json             # optional Gmail token; never commit
├── project-brain.db
├── project-brain.lock
├── logs/
├── results/
└── worktrees/<project-id>/<task-id>/
```

Override it for testing or a separate installation:

```bash
export PROJECT_BRAIN_RUNTIME_ROOT=/temporary/project-brain-runtime
```

Tests always provide a temporary runtime root and never write to the real home
directory.

## Configure projects

Copy the example and edit only the runtime copy:

```bash
mkdir -p ~/.project-brain/config
cp config/bridge-config.example.json ~/.project-brain/config/bridge-config.json
```

Every project needs a stable `project_id`. `repo_path` can change later without
changing task identity. `worktree_root` is optional and defaults to the runtime
layout. Commands are arrays; remote tasks cannot supply arbitrary shell text.

Load the runtime config on the first `apply`, or import a Bridge v2 config
explicitly:

```bash
project-brain migrate bridge-v2 \
  --config ./experiments/gmail-inbox/bridge-config.json
```

Migration reads and imports project definitions. It does not edit or delete the
source config, `processed.json`, `failures.json`, results, OAuth files, or old
logs. See [`docs/migration-bridge-v2.md`](docs/migration-bridge-v2.md).

## Operate Core

```bash
project-brain status
project-brain status --json
project-brain projects list
project-brain projects list --json
project-brain tasks list
project-brain tasks show <task-id> --json
project-brain health
project-brain health --json
project-brain cleanup --dry-run
project-brain cleanup --execute
project-brain apply --json
```

`cleanup` defaults to dry-run. Real cleanup requires `--execute`, takes the
runtime lock, and only acts on a registered terminal worktree whose resolved
path remains strictly under the configured root. Reviewable and active tasks
are retained. Remote branches and PRs are never deleted.

## State and review flow

The execution path is:

```text
pending -> running -> awaiting_review
                   -> verification_failed
                   -> retry_pending
                   -> failed
```

Review can move a task through `needs_changes`, `ready_to_merge`, `merging`, and
finally `accepted`. Core MVP defines these transitions but intentionally has no
automatic merge command. `accepted`, `failed`, `superseded`, and `expired` are
terminal for automatic execution.

Each acceptance criterion may include its own command:

```json
{
  "id": "tests",
  "text": "The regression suite passes",
  "command": ["python", "-m", "unittest", "discover", "-s", "tests"]
}
```

A criterion without an executable check is stored as `not_verified`, not
silently marked passed. Project-wide commands are separate evidence records.

## Gmail compatibility entry

The existing launcher remains available:

```bash
experiments/gmail-inbox/run_v2.sh dry-run
experiments/gmail-inbox/run_v2.sh apply
```

Set `PB_ALLOWED_SENDER` to the exact trusted sender first. Core ships no personal
sender default.

New Gmail JSON may include `task_id`, `dedupe_key`, `revision`, `expires_at`, and
`supersedes`. Legacy JSON remains accepted; a stable task ID is derived from the
Gmail message ID and a compatibility warning is recorded. A scan imports every
valid message, then an apply process executes at most one queued task.

OAuth defaults to runtime config paths. Existing token locations can be used
during migration without copying:

```bash
export PB_GMAIL_CREDENTIALS=/path/to/legacy/credentials.json
export PB_GMAIL_TOKEN=/path/to/legacy/token.json
```

## Scheduled execution

Install code at the documented stable app location, customize the supplied
launchd template if needed, and schedule `bridge_v2.py --apply`. Each launch
imports mail, executes no more than one task, and exits. There is no long-lived
Python polling loop; launchd reloads current code on the next interval.

## Recovery and troubleshooting

Use `project-brain health`, then `tasks show <task-id> --json`. Do not infer
liveness from a lock file: Core tests the actual flock, task state, registered
worktree, owner PID, and heartbeat. Detailed recovery steps and error categories
are in [`docs/troubleshooting-recovery.md`](docs/troubleshooting-recovery.md).

## Test

```bash
PYTHONPATH=src python -m compileall -q src tests experiments/gmail-inbox
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python experiments/gmail-inbox/test_bridge_v2.py -v
```

All tests use temporary repositories, bare remotes, and runtime roots. They do
not require Gmail, GitHub, Codex, or the user's home directory.
