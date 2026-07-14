# Troubleshooting and recovery

Start with read-only checks:

```bash
project-brain health --json
project-brain status --json
project-brain tasks show <task-id> --json
project-brain tasks recover <task-id> --dry-run --json
project-brain cleanup --dry-run --json
```

## Interrupted `running` tasks

Startup `apply` performs reconciliation while holding the runtime flock. To run
it explicitly:

```bash
project-brain tasks recover <task-id> --execute --json
```

Recovery uses PID plus heartbeat, durable attempt phase, registered worktree,
branch, HEAD, status, conflict state, origin, and canonical commit. Safe state
becomes `retry_pending` or `awaiting_review`. Unsafe state becomes `failed`; its
worktree is deliberately retained. Do not delete or reset that worktree before
collecting evidence.

## `task_history`

The task changed branch, rewrote history, entered a conflict/in-progress state,
or verification changed sealed Git state. Publication is blocked. Origin,
fetch configuration, and the remote default ref are restored when possible
because Git worktrees share repository configuration. File and commit evidence
is retained for inspection.

## `verification_failed`

Each result records a criterion, trusted verification ID where applicable,
exit status, summary, and private artifact path. A criterion without a trusted
command is `not_verified`, not passed. Record structured findings and a
`needs_changes` verdict to start a new implementation attempt.

## Remote recovery

An `awaiting_review` worktree may have been released after push/PR creation.
For later changes Core fetches only the registered branch, requires its remote
SHA to equal the stored canonical commit, checks base ancestry, recreates the
local worktree, and reuses the stored or discovered Draft PR. A similarly named
unknown branch is never adopted.

## Safe cleanup

`cleanup` defaults to dry-run. `--execute` takes the runtime lock and removes
only registered terminal worktrees whose resolved path remains within the
managed runtime root and whose owner is inactive. It removes the local task
branch after `git worktree remove`/`prune`; remote branches and PRs are never
deleted. Main checkout state is never changed.

The lock file is diagnostic metadata, not liveness proof. Never delete it to
force execution; test the flock and inspect the recorded owner instead.
