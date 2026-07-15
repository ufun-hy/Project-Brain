# Project Brain Core MVP

Project Brain Core is a local task control plane. It persists canonical tasks,
runs them in isolated Git worktrees, records independent verification evidence,
and publishes Draft pull requests without automatically accepting or merging
them.

The existing live Gmail Bridge under `experiments/gmail-inbox/` is frozen legacy
behavior and is not part of the Core architecture. This change does not modify,
migrate, launch, or replace it. Project Brain 0.4.0 adds a separate, controlled
MCP adapter for canonical Core operations; it does not copy DevSpace's arbitrary
file or terminal authority.

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
- Codex runs in a dedicated process group. Child PID/PGID, process birth and
  executable identity, and a live heartbeat are persisted, so an orphaned or
  identity-ambiguous child blocks every new task claim, not only a retry of its
  own task.
- Verification evidence belongs to an immutable, attempt-scoped verification
  set bound to one canonical head. Publication retries reuse that exact set.
- Review verdict validation, findings, task transition, phase update, and event
  are committed in one transaction.
- Verification runs behind a Git state seal. File, commit, branch, origin,
  fetch-config, conflict, remote default-ref, or local default-branch-ref
  mutations block publication. A changed human-owned local default branch is
  detect-only and is never restored, deleted, or rewound.
- Publishing pushes only the registered task branch and creates or reuses a
  Draft PR after exact base/head/SHA/repository validation. Core never merges
  automatically.

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
project-brain tasks recover <task-id> --execute --terminate-agent --json
project-brain tasks recover <task-id> --execute --confirm-no-agent --json
project-brain tasks recover <task-id> --execute --resume --json
project-brain tasks recover <task-id> --execute --cancel --json
project-brain health --json
project-brain apply --json
project-brain cleanup --dry-run --json
project-brain cleanup --execute --json
project-brain serve --host 127.0.0.1 --port 7677
```

## MCP adapter

The Streamable HTTP endpoint is `http://127.0.0.1:7677/mcp`. The no-auth MVP
rejects every non-loopback bind. ChatGPT access uses OpenAI Secure MCP Tunnel;
do not expose the local endpoint as an unauthenticated public service.

The eight allowlisted tools cover health, projects, canonical task create,
asynchronous queue dispatch, bounded task list/detail, exact-head review, and
read-only recovery preview. They expose no shell, arbitrary files, cleanup,
recovery resolution, acceptance, or merge operation. Dispatch starts a fixed
one-shot Core worker and returns immediately; `RuntimeLock` and the global
claim gate remain authoritative.

Setup, tool contracts, Secure MCP Tunnel steps, and the manual acceptance
checklist are in [`docs/mcp-adapter.md`](docs/mcp-adapter.md). Architecture and
threat boundaries are in
[`docs/rfc/RFC-004-mcp-adapter.md`](docs/rfc/RFC-004-mcp-adapter.md).

`apply` claims at most one task while holding the runtime flock. Startup
reconciliation restores safe interrupted work to `retry_pending` or
`awaiting_review`. A live persisted Codex process group is left running and no
other task is claimed. Recovery exposes a structured global claim report; if
any task remains `running` or `recovery_blocked`, `apply` returns `blocked`
with `claim_blockers` before `claim_next()`. `--terminate-agent` is the explicit
operator action that terminates/kills the whole group before recovery, but only
after the persisted birth/executable identity is re-verified immediately
before each signal.

If startup has no persisted child PID after a five-minute grace period, or a
live PID/PGID no longer matches its process identity, the task moves to
`recovery_blocked` and retains its worktree. It cannot be claimed
automatically. After inspecting the host, an operator must explicitly use
`--confirm-no-agent` or `--resume` to return it to `retry_pending`, or
`--cancel` to make it terminal. Each resolution is recorded as an event.

Before claiming new work, startup also preflights terminal worktrees. It writes
private, manifest-hashed failure evidence under `results` first, records the
archive in SQLite, and only then removes the safe managed worktree. Archive
failure or any PID/path/state safety failure retains the worktree.

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
├── results/<task-id>/                   0700
│   ├── attempt-<N>/verification-set-*/  0700 / 0600
│   └── forensics/worktree-*/            0700 / 0600
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
