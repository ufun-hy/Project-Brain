# Migrate Bridge v2 to Core MVP

Core migration is additive and reversible. Do not delete Bridge v2 files until
the new runtime has been reviewed over real tasks.

## 1. Stop overlapping polling

Unload or stop any old long-lived `daemon.py` process. Keep the launchd job
disabled until Core health checks pass. Manual and scheduled Core runs share one
flock, but the legacy daemon does not know about that lock.

## 2. Preserve legacy state

Keep these files unchanged:

- `bridge-config.json`
- `processed.json`
- `failures.json`
- `results/`
- `credentials.json`
- `token.json`
- old logs

Core does not interpret old processed/failure JSON as canonical task state. This
avoids incorrectly turning a Gmail message ID into permanent task identity.

## 3. Import registered projects

```bash
project-brain migrate bridge-v2 \
  --config /path/to/experiments/gmail-inbox/bridge-config.json \
  --json
```

The command creates stable IDs from legacy project names, resolves repository
and remote information, and stores the project records in SQLite. It reads but
does not modify the legacy file. Repeating the import is safe.

For new installations, copy `config/bridge-config.example.json` to
`~/.project-brain/config/bridge-config.json` and choose explicit permanent
`project_id` values.

## 4. Point Gmail OAuth at runtime state

Either copy credentials deliberately into `~/.project-brain/config/` or keep
using legacy files through `PB_GMAIL_CREDENTIALS` and `PB_GMAIL_TOKEN`. Core
never automatically moves or deletes tokens.

## 5. Verify before scheduling

```bash
project-brain projects list --json
project-brain health --json
project-brain status --json
experiments/gmail-inbox/run_v2.sh dry-run
```

Dry-run reads and validates Gmail messages without inserting or executing them.

## 6. Enable one-shot scheduling

Use launchd `StartInterval` with `bridge_v2.py --apply`. Each process imports all
visible valid messages, claims at most one task, and exits. Do not run the old
polling daemon beside the scheduled one-shot command.

## Rollback

Stop the Core launchd job. The legacy JSON and OAuth files remain untouched and
can still be inspected. Any Core-created task worktree stays registered in the
SQLite database; preview it with `project-brain cleanup --dry-run` before any
explicit cleanup. Core never deletes a remote branch or Draft PR during rollback.
