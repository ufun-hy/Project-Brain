# Troubleshooting and recovery

Start with:

```bash
project-brain health --json
project-brain status --json
project-brain tasks show <task-id> --json
project-brain cleanup --dry-run --json
```

## `already_running`

Another process holds the runtime flock. The lock file is only metadata; do not
delete it to force execution. Find the PID shown in the file and confirm the
process state. A released or stale file does not block a new flock holder.

## `git_fetch`

Fetch failure is transient. Confirm network access, repository `origin`, SSH
credentials, and the registered default branch. The task becomes
`retry_pending` until the configured transient-attempt limit; Core does not
switch or clean the main checkout while testing recovery.

## `no_changes`

The agent produced neither net file changes nor new commits. This is permanent
for that execution and is not automatically retried. Correct the task input by
creating a new revision.

## `task_history`

Core detected a branch switch, detached HEAD, non-fast-forward rewrite,
unresolved conflict, or in-progress merge/cherry-pick/rebase state. It refuses
to rewrite unknown history. Inspect the task event and attempt records. Create a
new task revision rather than force-resetting the registered main checkout.

## `verification_failed`

The worktree and evidence are retained. Read each result under `verification`
and its runtime artifact. Decide whether the criterion or implementation needs
changes, then move the task through the review flow. A project-wide passing
command does not mark unrelated criteria passed.

## Interrupted `running` task

SQLite preserves its attempt, worktree registration, owner PID, heartbeat, and
events. An unexpired running task is never claimed again automatically. Confirm
the process is gone and review its working tree before deliberately expiring or
superseding it. Do not infer a crash only from a leftover lock file.

## Safe cleanup

`cleanup --dry-run` reports `would_clean` or `retained` with a reason. Real
cleanup requires `--execute` and the runtime lock. Core requires all of:

- registered project and worktree records;
- a terminal task state;
- no live foreign owner PID;
- a usable heartbeat decision;
- a resolved path strictly below the configured worktree root;
- no symlink escape.

After `git worktree remove`, Core runs `git worktree prune` and removes only the
local task branch. It never deletes the remote branch/PR and never runs
`reset`, `clean`, or `checkout` in the registered main checkout.
