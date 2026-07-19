# Troubleshooting and recovery

Start with read-only checks:

```bash
project-brain health --json
project-brain status --json
project-brain tasks show <task-id> --json
project-brain tasks recover <task-id> --dry-run --json
project-brain cleanup --dry-run --json
```

Ordinary App users should open **Diagnostics** or the task detail instead of
running these developer/operator commands manually.

## Local task planning and creation

The local task sheet keeps errors visible and offers a recovery action. If the
project revision/hash, remote Base SHA, readiness, delivery policy, plan hash,
supersession state, or ten-minute expiry changed after review, select **Review
new plan**. Core will not apply a stale token. A repeated or concurrent second
confirmation fails closed; open Task Center to inspect the authoritative task.
Never work around a conflict by deleting SQLite state.

If readiness is blocked, use **Open Diagnostics** and repair the managed helper,
Worker, project intake, Git repository, Codex executable, or GitHub publication
prerequisite named by the plan. MCP, Tunnel, Gmail, and external ChatGPT
acceptance are not local-task readiness conditions.

An Analyze task may complete with no changed files. Its authoritative terminal
state is `completed`, with a schema-v1 `analysis` result in Task Center. Do not
reinterpret a clean worktree as `Task produced no changes` failure. Implement
tasks retain the existing verification, publication, review, and recovery
states.

## Interrupted `running` tasks

Startup `apply` performs reconciliation while holding the runtime flock. To run
it explicitly:

```bash
project-brain tasks recover <task-id> --execute --json
```

Recovery uses PID/PGID plus persisted process birth and executable identity,
heartbeat, durable attempt phase, registered worktree, branch, HEAD, status,
conflict state, origin, and canonical commit. Safe state becomes
`retry_pending` or `awaiting_review`. If a process-group member is alive,
recovery waits and does not claim any task. `apply --json` returns `blocked`,
`claim_safe: false`, and a `claim_blockers` list while any task remains
`running` or `recovery_blocked`.

To explicitly stop an orphaned agent, terminate the entire persisted group and
then reconcile it:

```bash
project-brain tasks recover <task-id> --execute --terminate-agent --json
```

The command re-verifies process birth time, executable, command digest, PID, and
PGID immediately before signalling. An absent or mismatched identity sends no
signal and moves the task to `recovery_blocked`.

If child startup was interrupted before PID persistence, Core waits for a
five-minute grace period and then moves the task to `recovery_blocked`. It keeps
the worktree and never starts a replacement attempt automatically. Inspect the
host and choose one explicit resolution:

```bash
project-brain tasks recover <task-id> --execute --confirm-no-agent --json
project-brain tasks recover <task-id> --execute --resume --json
project-brain tasks recover <task-id> --execute --cancel --json
```

`--confirm-no-agent` and `--resume` return the task to `retry_pending` after an
operator assertion; `--cancel` makes it terminal. Each action is persisted in
the event log. Until that resolution removes the `recovery_blocked` state, the
global single-agent gate prevents unrelated pending tasks from starting.

## `task_history`

The task changed branch, rewrote history, entered a conflict/in-progress state,
or verification changed sealed Git state. Publication is blocked. Origin,
fetch configuration, the remote default ref, and the shared local default
branch ref are sealed because Git worktrees share repository configuration.
Origin, fetch configuration, and the remote tracking ref are restored when
possible. The human-owned local default branch is detect-only and is left
exactly as found; it is never rewound or deleted. File and commit evidence is
retained for inspection.

## `verification_failed`

Each result records a criterion, trusted verification ID where applicable,
exit status, summary, and private artifact path. Results are written with
exclusive creation below an attempt-scoped verification set bound to the exact
canonical head. Publication retry uses the task's stored set ID, not the
current attempt count or all historical evidence. A criterion without a trusted
command is `not_verified`, not passed. Record structured findings and a
`needs_changes` verdict to start a new implementation attempt.

## Remote recovery

An `awaiting_review` worktree may have been released after push/PR creation.
For later changes Core fetches only the registered branch, requires its remote
SHA to equal the stored canonical commit, checks base ancestry, recreates the
local worktree, and reuses the stored or discovered Draft PR. A similarly named
unknown branch is never adopted.

## Safe cleanup

`cleanup` defaults to dry-run. `--execute` takes the runtime lock and first
captures metadata, branch, HEAD, status, conflicts, tracked/staged diffs, and
untracked files in a private manifest-hashed archive. Only after that archive is
persisted may it remove a registered terminal worktree whose resolved path is
within the managed runtime root and whose Bridge and Codex owners are inactive.
Archive failure retains the worktree. Cleanup removes the local task branch
after `git worktree remove`/`prune`; remote branches and PRs are never deleted.
Main checkout state is never changed.

The lock file is diagnostic metadata, not liveness proof. Never delete it to
force execution; test the flock and inspect the recorded owner instead.
