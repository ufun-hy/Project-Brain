# Project Brain Core MVP

Project Brain Core is a local task control plane. It persists canonical tasks,
runs them in isolated Git worktrees, records independent verification evidence,
and publishes Draft pull requests without automatically accepting or merging
them.

The existing live Gmail Bridge under `experiments/gmail-inbox/` is frozen legacy
behavior and is not part of the Core architecture. This change does not modify,
migrate, launch, or replace it. A future MCP/DevSpace source adapter will be a
separate project.

## Guarantees

- Stable project, task, dedupe, criterion, and verification IDs are validated
  before persistence.
- Mutable runtime data is private and lives outside source under
  `~/.project-brain/` by default.
- Every implementation runs under
  `<runtime>/worktrees/<project-id>/<task-id>/`; the registered main checkout is
  never checked out, reset, cleaned, or used as an agent working directory.
- External tasks can describe criteria and reference trusted project
  `verification_id` values. They cannot provide executable `command` or `argv`.
- Implementation, verification, publication, and review are durable attempt
  phases. A `needs_changes` verdict reruns implementation and appends a new
  canonical commit.
- Interrupted processes are reconciled from PID, heartbeat, phase, worktree,
  branch, HEAD, status, origin, and registered remote state.
- Verification runs behind a Git state seal. File, commit, branch, origin,
  fetch-config, conflict, or default-ref mutations block publication.
- Publishing pushes only the registered task branch and creates or reuses a
  Draft PR. Core never merges automatically.

## Install and configure

Python 3.10+, Git, Codex (or another explicitly configured local agent), and
GitHub CLI are required. `gh` is needed only when automatic PR creation is
enabled.

```bash
python3.11 -m venv ~/.project-brain/app/venv
~/.project-brain/app/venv/bin/pip install -e .
mkdir -p ~/.project-brain/config
cp config/project-brain.example.json ~/.project-brain/config/project-brain.json
```

The actual repository `origin` must match the registered `remote_url`.
`worktree_root` is deliberately not configurable outside the managed runtime
path.

## Canonical enqueue

Source adapters translate their messages into a canonical JSON envelope and use
the source-neutral CLI:

```bash
project-brain tasks enqueue --file ./task.json --json
```

Example:

```json
{
  "task_id": "core-recovery-1",
  "project_id": "project-brain",
  "dedupe_key": "core-recovery",
  "revision": 1,
  "source_type": "local-import",
  "goal": "Implement deterministic recovery",
  "task_type": "codex",
  "acceptance_criteria": [
    {
      "id": "tests-pass",
      "text": "The Core regression suite passes",
      "verification_id": "core-tests"
    }
  ],
  "payload": {
    "prompt": "Implement deterministic recovery and add tests."
  }
}
```

Only the command registered as `core-tests` is executable. A criterion without
a `verification_id` is recorded as `not_verified` for human review.

## Operate

```bash
project-brain status --json
project-brain projects list --json
project-brain tasks list --json
project-brain tasks show <task-id> --json
project-brain tasks recover <task-id> --dry-run --json
project-brain tasks recover <task-id> --execute --json
project-brain health --json
project-brain apply --json
project-brain cleanup --dry-run --json
project-brain cleanup --execute --json
```

`apply` claims at most one task while holding the runtime flock. Startup
reconciliation restores safe interrupted work to `retry_pending` or
`awaiting_review`; unsafe state becomes `failed` and its worktree is retained
for forensics.

Review findings are JSON bound to the current canonical `head_sha`:

```json
{
  "head_sha": "<canonical-sha>",
  "verdict": "needs_changes",
  "findings": [
    {
      "severity": "blocker",
      "file": "src/project_brain/recovery.py",
      "evidence": "Interrupted verification is left running.",
      "requirement": "Reconcile it deterministically on startup."
    }
  ]
}
```

```bash
project-brain tasks review <task-id> --file ./review.json --json
```

Active findings are included in the next Codex prompt. They automatically stop
being active after a new canonical commit changes the task head.

## Runtime layout and permissions

```text
~/.project-brain/                         0700
├── config/project-brain.json
├── project-brain.db                     0600
├── project-brain.lock                   0600
├── logs/                                0700
├── results/<task-id>/...                0700 / 0600
└── worktrees/<project-id>/<task-id>/    0700
```

Override the root for tests or isolated installations with
`PROJECT_BRAIN_RUNTIME_ROOT`. Result and worktree paths reject traversal and
symlink escape.

## Validation

```bash
scripts/verify-core.sh
```

The same command runs in CI. Tests use temporary repositories, bare remotes,
and runtime roots; no Gmail, GitHub, Codex, or user-home credentials are needed.

Architecture and recovery details are in
[`docs/rfc/RFC-003-core-v3.md`](docs/rfc/RFC-003-core-v3.md) and
[`docs/troubleshooting-recovery.md`](docs/troubleshooting-recovery.md).
