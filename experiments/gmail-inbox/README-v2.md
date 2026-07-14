# Project Brain Gmail compatibility adapter

Bridge v2 is now an input adapter for Project Brain Core:

```text
Gmail message -> parse/validate -> canonical task -> SQLite TaskStore
                                                  -> Core executes one task
```

It no longer checks out branches, runs Codex, commits, pushes, or creates PRs
inside the Gmail adapter. Those responsibilities belong to Core and always run
in a registered task worktree.

See the repository [`README.md`](../../README.md) for installation and runtime
configuration, and [`docs/migration-bridge-v2.md`](../../docs/migration-bridge-v2.md)
for the no-delete migration path.

## Run

```bash
./run_v2.sh dry-run
./run_v2.sh apply
```

Dry-run reads and validates without inserting. Apply imports all valid messages,
claims at most one queued task under the runtime lock, and exits.

OAuth defaults to:

```text
~/.project-brain/config/credentials.json
~/.project-brain/config/token.json
```

Set `PB_GMAIL_CREDENTIALS`, `PB_GMAIL_TOKEN`, or
`PROJECT_BRAIN_RUNTIME_ROOT` to override local paths. Never commit these files.
Set `PB_ALLOWED_SENDER` explicitly to the exact trusted sender before every
manual or scheduled run; no personal address is built into the source.

## Task identity

New JSON supports:

```json
{
  "task_id": "pb-example-v2",
  "project_id": "project-brain",
  "dedupe_key": "pb-example",
  "revision": 2,
  "supersedes": "pb-example-v1",
  "expires_at": "2099-01-01T00:00:00Z",
  "type": "codex",
  "goal": "Implement the reviewed revision",
  "prompt": "Implement and test the reviewed revision."
}
```

Legacy `type`, `project`, `prompt/files/command`, and commit/PR fields remain
accepted. Missing `task_id` receives a reproducible compatibility ID derived
from Gmail `message_id` plus an audit warning.
