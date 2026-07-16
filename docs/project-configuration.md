# Project configuration operations

## First project

Initialize the private runtime, then register a real Git checkout. `projects
add` resolves the checkout to an absolute real path, verifies `origin`, detects
the remote default branch, derives a stable project ID when omitted, resolves
the Codex executable, assigns only the managed runtime worktree root, prints a
plan, and asks for confirmation unless `--non-interactive` is used.

```bash
project-brain init --json
project-brain projects add ~/code/example --project-id example --json
project-brain projects show example --json
project-brain projects check example --json
```

Codex argv[0] is resolved once to an absolute executable path and checked for
execute permission before any project write. Declarative files may omit
`codex_command` to use `codex` from the onboarding process PATH. Exported files
always contain the resolved absolute command. In interactive JSON mode, the
plan and confirmation prompt are written to stderr; stdout is one final JSON
object. Add `--non-interactive` in scripts.

`projects check` is read-only. It checks the repository, origin, default branch,
Codex and optional `gh`, the managed worktree boundary, and whether each trusted
verification executable exists. It never runs a verification command.

Use a JSON array in `--verification-file`; entries have `id`, `text`, `command`
as an argv array, and optional `always_run`. Shell strings are never accepted.
Credentials must come from the process environment, credential manager, or
`gh` login; literal tokens and credential-bearing remotes are rejected.

## Revisions and existing tasks

`projects update` prints current/next revision and hash, changed fields,
nonterminal task count, and the snapshot effect before confirmation. A no-op or
display-name-only update does not increment the execution revision. Existing
tasks always keep the snapshot they received at creation; only later tasks bind
the new revision. There is intentionally no project delete command in 0.5.0.

## Declarative config

Start from `config/project-brain.example.json` and use this sequence:

```bash
project-brain config validate --file ./project-brain.json --json
project-brain config plan --file ./project-brain.json --json
project-brain config apply --file ./project-brain.json --execute --json
project-brain config status --json
project-brain config export --file ./backup.json --json
```

Validation and planning do not register, update, or remove projects. Apply is
add/update/no-op only and is all-or-nothing across the file. Omitted database
projects are reported as `registered_only`. Export is private and atomic;
without `--force`, its commit is an atomic no-replace operation, and repeat
export or a concurrently created destination is rejected.

## Migration and rollback

Before upgrading a long-lived runtime, stop the MCP server and workers and make
a filesystem-level copy of `project-brain.db`. The first 0.5.0 command migrates
schema v4 to v5 atomically and backfills revision 1 plus every task snapshot.
Relative legacy Codex commands are resolved to absolute paths during migration
when possible. An unresolvable command is marked
`schema_v5_migration_requires_operator_update`; project checks report unhealthy,
task execution fails closed, and export is blocked until `projects update
--codex-path ...` installs a valid absolute executable. On failure the
transaction rolls back and retry is safe. To return to 0.4.0,
stop 0.5.0 and restore the pre-upgrade database copy; do not manually downgrade
the live database.

## Troubleshooting snapshots

- `Task execution snapshot is missing or invalid`: restore the database from a
  known-good backup or supersede the task with a new canonical task. Do not copy
  the active project profile into the old task.
- `Task execution snapshot hash mismatch`: treat this as database tampering or
  corruption. Stop execution, preserve the database and forensic evidence, and
  investigate before restoring.
- A retry uses an older branch, verification set, Codex command, or publication
  policy: this is expected when that task was created before a project update.
  Create a new task revision if the new configuration must apply.
- `legacy_schema`: inspect the plan. Explicit bootstrap is allowed only for an
  empty registry; otherwise export a schema-v1 file and reconcile it normally.
