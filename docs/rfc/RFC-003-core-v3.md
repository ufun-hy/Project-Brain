# RFC-003: Project Brain Core v3

Status: Implemented by Core MVP
Created: 2026-07-14
Type: Architecture RFC

## Problem

Bridge v2 proved the Gmail-to-Draft-PR workflow, but it couples transport,
execution, repository mutation, and mutable runtime state. It also treats a
Gmail message as task identity and assumes a dirty working tree is the only
proof that Codex produced work. Those assumptions prevent safe multi-project
operation and reliable recovery.

## Decision

Project Brain Core is a local control plane with explicit adapter boundaries:

```text
GmailAdapter ──> TaskStore <── StatusCLI
                    │
                TaskEngine
             ┌──────┼──────────┐
      WorktreeManager     CodexAdapter
             │                 │
             └──── Git history normalizer
                    │
              ReviewEvidence
```

Transport adapters only create canonical tasks. `TaskEngine` owns task
orchestration and state transitions. Persistence is behind `TaskStore`.
Repository mutations happen only inside a task worktree managed by
`WorktreeManager`.

## Runtime boundary

The default runtime root is `~/.project-brain/` and can be overridden by
`PROJECT_BRAIN_RUNTIME_ROOT` or an explicit CLI/test argument:

```text
~/.project-brain/
├── config/bridge-config.json
├── project-brain.db
├── project-brain.lock
├── logs/
├── results/
└── worktrees/<project-id>/<task-id>/
```

Runtime files, tokens, logs, databases, results, and worktrees do not belong in
Git. OAuth and GitHub credentials remain owned by their existing local tools;
Core never persists them.

## Data model

### Project

`project_id` is the stable identity. A project records its display name,
repository path, remote URL, default branch, worktree root, Codex command,
verification commands, push/PR policy, and timestamps. A local path can change
without changing project identity.

### Task

A task records stable `task_id`, `project_id`, logical `dedupe_key`, `revision`,
source metadata, goal, acceptance criteria, status, attempt count, task branch,
base/head SHAs, worktree path, agent session, canonical commit, PR URL, most
recent error, expiry, and supersession relationship. Type-specific adapter
input is stored as validated JSON payload, separate from the identity fields.

`task_id` is idempotent. `(project_id, dedupe_key, revision)` is also unique.
A newer task can explicitly supersede an older non-accepted task. Gmail
`message_id` is only source metadata.

### Durable audit records

SQLite contains versioned tables for projects, tasks, attempts, worktrees,
agent sessions, verification results, and append-only events. State transitions
and task claiming use transactions. Repeated schema initialization is safe and
future migrations append a new schema version.

## State machine

Core defines these states:

```text
pending -> running
running -> awaiting_review | verification_failed | retry_pending | failed | expired
verification_failed -> running | needs_changes | superseded | expired
retry_pending -> running | failed | superseded | expired
awaiting_review -> needs_changes | ready_to_merge | superseded | expired
needs_changes -> running | superseded | expired
ready_to_merge -> merging | needs_changes | superseded
merging -> accepted | merge_failed
merge_failed -> merging | needs_changes | failed
```

`accepted`, `failed`, `superseded`, and `expired` are terminal for automatic
execution. Core MVP defines merge/review transitions but does not automatically
approve or merge. A successful execution always stops at `awaiting_review`.

Expired pending or recoverable tasks are moved to `expired` before claiming.
An unexpired `running` task is never claimed again. Error classes, not a global
retry counter, decide whether a failure becomes `retry_pending` or `failed`.

## Worktree policy

Before creation, Core fetches `origin/<default-branch>` without checking out or
cleaning the registered main repository. The task worktree and deterministic
branch `brain/<sanitized-task-id>` are bound to the task record and latest
remote base SHA. Codex runs only in that path.

Worktrees are retained for `awaiting_review`, `needs_changes`,
`verification_failed`, and recoverable failures so review or repair can
continue. Terminal worktrees can be cleaned. Cleanup requires a registered
worktree, a terminal task, an inactive owner process or stale heartbeat, and a
resolved path strictly below the configured project worktree root. Symlink
escape and unregistered paths are rejected. Cleanup uses `git worktree remove`
followed by `git worktree prune`; it never resets, cleans, or checks out the
registered main checkout.

## Codex and Git history

The adapter records the expected branch, base SHA, initial HEAD, and initial
working status. After execution Core rejects:

- a different branch;
- unresolved merge/cherry-pick/rebase state or unmerged paths;
- a HEAD for which the base or initial HEAD is no longer an ancestor.

If the history is safe, Core soft-resets commits made during the current attempt
to that attempt's initial HEAD, stages all attempt-local changes, and creates
one canonical commit. On the first attempt the initial HEAD is the recorded
base; later review revisions append a canonical commit without rewriting pushed
history. This
normalizes uncommitted edits, one or more Codex commits, and ordinary
cherry-picks. No commit and no working change raises a permanent
`NoChangesError`; unsafe history raises `TaskHistoryError` and is never
automatically rewritten.

## Verification and review boundary

Each acceptance criterion receives its own `passed`, `failed`, or
`not_verified` record with evidence metadata. Core does not infer that every
criterion passed from a project-wide command. Project verification commands are
stored as distinct evidence records. Failed commands enter
`verification_failed`; successful execution with recorded evidence enters
`awaiting_review`. ChatGPT reviews the evidence and the user controls acceptance
and merge authorization.

## Process model

Manual and scheduled runs use the same `fcntl.flock` lock under the runtime
root. A second process reports structured `already_running` state. One apply
process transactionally claims at most one task, executes it, and exits so the
next scheduled process loads current code. The lock file is diagnostic metadata,
not sufficient proof that a process or task is active.

## Gmail compatibility

Gmail remains a read-only input adapter:

```text
message -> parse and validate -> canonical task -> TaskStore
```

New messages may provide `task_id`, `dedupe_key`, `revision`, `expires_at`, and
`supersedes`. For legacy JSON, a reproducible task ID is derived from the Gmail
message ID and a compatibility warning is recorded. A scan may enqueue multiple
messages; execution remains one task per process.

## Non-goals

Core MVP does not add a menu bar product, web console, public MCP tunnel,
multi-agent execution, automatic merge, team permissions, billing, or template
marketplace. DevSpace is not a dependency.
