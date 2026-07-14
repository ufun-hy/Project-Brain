# RFC-003: Project Brain Core v3

Status: Implemented; Draft PR under review
Updated: 2026-07-14
Type: Architecture RFC

## Decision

Project Brain Core is a source-neutral local control plane:

```text
Source adapter -> Canonical ingress -> TaskStore <- Status/review CLI
                                      |
                                  TaskEngine
                         +------------+------------+
                    Worktrees       Codex      Verification
                         +------------+------------+
                                      |
                              Draft PR publication
```

The existing live Gmail Bridge is frozen legacy software. It is not a Core
adapter, is not modified by this implementation, and will not be migrated or
re-launched by Core. A future MCP/DevSpace adapter is a separate decision.

## Trust boundaries

Source adapters may submit stable IDs, descriptions, task payloads, and
acceptance criteria. They cannot submit executable verification commands or
argv. A criterion may reference a stable `verification_id`; Core resolves it
only against commands in trusted local project configuration.

`command` tasks similarly carry only a local allowlist name. Project
configuration supplies the argv. Codex commands and verification commands must
not contain literal credentials. Persisted errors and output artifacts are
redacted.

## Runtime and repository ownership

All mutable state is under an overridable runtime root. Directories are mode
`0700`; the SQLite database, lock, logs, and result files are mode `0600`.
Result and worktree components use strict stable IDs and resolved containment
checks. Absolute paths, traversal, and symlink escape are rejected.

Each project has exactly one permitted worktree root:
`<runtime>/worktrees/<project-id>/`. Core verifies that the repository's actual
`origin` matches the registered remote before fetch, verification, and
publication. The registered main checkout can be dirty and is never switched,
reset, cleaned, or used as an execution directory.

## Durable model and migrations

SQLite schema v2 stores projects, tasks, attempts, worktrees, agent sessions,
verification evidence, reviews, structured review findings, and append-only
events. Migrations execute statement-by-statement inside one explicit
transaction. A failed migration rolls back fully, and a database newer than the
supported schema is rejected.

Stable `task_id`, `project_id`, `dedupe_key`, criterion IDs, verification IDs,
and supersession IDs use 1-128 letters, digits, dots, underscores, or hyphens.
`task_id` and `(project_id, dedupe_key, revision)` provide idempotency.

## Attempts and review revisions

Every attempt has an explicit phase:

```text
implementation -> verification -> publication -> review
```

A transient publication failure retains `publication` and retries only the
push/PR operation. A verification retry reruns trusted verification against the
same canonical commit. A `needs_changes` verdict resets the next attempt to
`implementation`, keeps the reviewed canonical commit as an ancestor, and
creates a new canonical commit.

Reviews are bound to the current canonical `head_sha`. Findings persist
`severity`, `file`, `evidence`, and `requirement`. Active findings are appended
to the next Codex prompt. Once a new canonical commit changes `head_sha`, older
findings remain auditable but are no longer active.

Success stops at `awaiting_review`. The user controls readiness, acceptance,
and merge authorization; Core does not merge automatically.

## Git normalization and verification seal

Before implementation, Core records expected branch, base, initial HEAD, and
clean status. It rejects branch switches, conflicts, in-progress operations,
rewrites, and any history where the base or initial HEAD is no longer an
ancestor. Safe attempt-local changes and commits are normalized into one
canonical commit appended after the prior canonical commit.

Before verification Core seals:

- task branch and canonical HEAD;
- full worktree status and conflict state;
- actual origin URL and origin fetch configuration;
- the remote default-branch ref.

The same state is checked after verification and again before publication.
File, commit, branch, origin, fetch configuration, conflict, or default-ref
mutation blocks push. Shared origin/fetch/default-ref metadata is restored to
its sealed value before the task fails; the task worktree is retained for
forensics.

## Crash and remote recovery

Startup reconciliation runs under the runtime flock before claiming a task. It
uses the registered owner PID, heartbeat, attempt phase, worktree path, branch,
HEAD, status, origin, default branch, and canonical commit.

- A live owner with a recent heartbeat remains `running`.
- Clean interrupted implementation, verification, or publication becomes
  `retry_pending` at its durable phase.
- Completed review publication becomes `awaiting_review`.
- Missing, dirty, conflicting, wrong-branch, wrong-HEAD, wrong-origin, or
  otherwise unsafe state becomes `failed` and is retained for forensics.

Operators can preview or execute the same logic with
`tasks recover <id> --dry-run|--execute`.

After a successful push and Draft PR lookup/creation, Core may release the
clean local review worktree and local task branch. It never deletes the remote
branch or PR. A later `needs_changes` attempt recreates the worktree only when
the registered remote branch exactly matches the stored canonical SHA and
descends from the registered base. Unknown or mismatched remote branches are
rejected.

## Non-goals

Core MVP does not add Gmail productization, a menu bar app, web console, public
MCP tunnel, multi-agent execution, automatic merge, team permissions, billing,
or a template marketplace.
