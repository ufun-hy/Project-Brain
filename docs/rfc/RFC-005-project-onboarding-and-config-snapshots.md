# RFC-005: Project onboarding and configuration snapshots

Status: implemented in Core 0.5.0

## Decision

SQLite is the sole runtime authority for registered projects. JSON is an
explicit import/export format, never a live configuration source. Project
registration and updates run under the global runtime flock. A configuration
file is fully parsed, structurally validated, checked for credential-like
values, normalized against its repositories, and planned before one atomic
SQLite transaction writes any project.

Each execution-affecting project configuration has a monotonic revision and a
SHA-256 over canonical, sorted, compact JSON. The execution profile comprises
the stable project ID, repository and origin, default branch, managed worktree
root, Codex argv, trusted verification argv, named local command allowlist, and
automatic push/PR flags. Display name is metadata: changing it does not change
the revision or hash.

Task creation selects the project row, validates referenced verification IDs,
and writes `project_config_revision`, `project_config_sha256`, and
`execution_profile_json` in the same `BEGIN IMMEDIATE` transaction. After that
point implementation, verification, publication retry, review revision,
recovery, worktree release/cleanup, and terminal forensics use only the task
snapshot. A missing, malformed, project-mismatched, or hash-mismatched snapshot
fails closed and never falls back to the active project row.

## Configuration lifecycle

The portable JSON format has `schema_version: 1` and a `projects` array.
Unknown top-level fields are rejected. `config validate` and `config plan` are
read-only. `config apply` requires `--execute`; projects omitted from the file
remain registered and are reported as `registered_only`. All projects are
prevalidated and the SQLite write is atomic. `config export` writes a mode-0600
temporary sibling, fsyncs it, renames it atomically, and refuses overwrite
without `--force`.

Schema-less Bridge-era JSON is identified only by `config plan` as
`legacy_schema`. It can be explicitly applied once when no project has ever
been registered. Neither the worker nor the MCP server silently imports it.

## Migration

Schema v5 adds revision/hash/source metadata to projects and immutable snapshot
columns to tasks. A Python data hook runs inside the same migration transaction
as the DDL. It canonicalizes every existing project at revision 1, then binds
every existing task to that profile. SQL or Python-hook failure rolls back DDL,
data, migration history, and `user_version`; reopening is idempotent. A database
newer than the supported schema remains rejected.

Rollback is application rollback, not destructive schema downgrade: stop Core,
restore the pre-migration database backup, and run the older binary. Never
delete v5 columns or rewrite task snapshots in place.

## MCP boundary

The adapter remains exactly eight tools and adds no configuration write tool.
Project summaries expose revision and a short hash; task summaries expose their
bound revision and short hash. Raw execution profiles, local paths, and argv are
not returned.
