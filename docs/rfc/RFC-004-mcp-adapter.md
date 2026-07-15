# RFC-004: MCP Adapter MVP

Status: Implemented; local verification complete, external tunnel acceptance pending
Updated: 2026-07-15
Target: Project Brain 0.4.0

## Decision

Project Brain exposes a narrow Model Context Protocol adapter for planning,
inspection, task intake, review, and one-shot dispatch. The adapter is a
long-running local process; Core execution remains the existing short-lived,
runtime-locked worker.

```text
ChatGPT -> OpenAI Secure MCP Tunnel -> 127.0.0.1:7677/mcp
                                             |
                                      MCP allowlisted tools
                                             |
                                   TaskStore / Core services
                                             |
                              fixed one-shot project-brain apply
```

The MCP server uses the official MCP Python SDK v1 stable line through
`mcp>=1.28,<2`. As of this decision, v1.28.1 is the latest stable release and
v2 is a breaking prerelease. FastMCP supplies protocol framing, JSON Schema,
tool discovery, and Streamable HTTP transport; Project Brain does not implement
JSON-RPC itself.

## Transport and exposure

`project-brain serve` listens on `127.0.0.1:7677` by default and serves
Streamable HTTP at `/mcp`. The MVP is stateless and returns JSON responses.
Only IP loopback literals `127.0.0.1` and `::1` are accepted as bind hosts;
names such as `localhost`, wildcard addresses, interface addresses, and DNS
names are rejected before the SDK starts. There is no adapter-level
authentication because the listener is private and loopback-only.

ChatGPT cannot connect to this listener directly. Operators use OpenAI Secure
MCP Tunnel, whose client makes an outbound HTTPS connection and forwards MCP
requests to the private HTTP endpoint. The adapter must never be exposed as an
unauthenticated public endpoint, and this RFC does not add a generic public
tunnel, reverse proxy, or port-forwarding recipe.

## Application boundary

MCP tools call a small adapter service that owns validation, redaction,
presentation limits, and audit behavior. The service reuses `TaskStore`,
`TaskImporter`, `RecoveryManager`, and the same status/health logic as the CLI;
it does not duplicate task state transitions or Git recovery rules.

The adapter exposes only these versioned tool names:

| Tool | Effect | Contract |
| --- | --- | --- |
| `project_brain_system_health` | read | Bounded health checks and task status counts |
| `project_brain_projects_list` | read | Registered project identity/capability summary; no commands or local paths |
| `project_brain_tasks_create` | write | Canonical Codex task intake with fixed `source_type=mcp` and `task_type=codex` |
| `project_brain_queue_dispatch_next` | write | Start at most one fixed one-shot worker when the runtime and claim gate permit |
| `project_brain_tasks_list` | read | Bounded task summaries; default 20, maximum 100 |
| `project_brain_tasks_get` | read | One bounded task detail view with recent events/evidence/reviews |
| `project_brain_tasks_review` | write | Atomically apply an exact-canonical-head review verdict |
| `project_brain_tasks_recovery_preview` | read | Dry-run recovery evidence only; no resolution or cleanup controls |

Read tools declare `readOnlyHint`. Create, review, and dispatch declare
side-effect annotations and do not claim idempotency where the operation may
create state or a process. Tool results use stable `status`, `code`, and
bounded `data` fields. Expected failures are returned as structured adapter
errors instead of tracebacks or unbounded Core objects.

## Input policy

Every tool schema rejects unknown top-level fields. Strings have explicit
length bounds, arrays have explicit item limits, and nested objects are scanned
before Core persistence. The create tool accepts only:

- stable task, project, dedupe, supersession, and criterion identifiers;
- revision, goal, and optional expiry;
- acceptance criteria containing only `id`, `text`, and optional trusted
  `verification_id`;
- a non-empty bounded Codex prompt.

The adapter fixes `source_type` to `mcp` and `task_type` to `codex`. At every
nesting depth it rejects `command`, `argv`, `shell`, `cwd`, `environment`,
`repo_path`, `worktree_path`, and `codex_command`. Credential-like input is
rejected before persistence. `task_id` and the Core logical key
`(project_id, dedupe_key, revision)` retain existing idempotent behavior.

Review accepts only `task_id`, exact `head_sha`, `approved|needs_changes`, and
bounded structured findings. It delegates the verdict, finding inserts, task
transition, phase update, and event to `TaskStore.apply_review_verdict()` so
the write remains one transaction. It never dispatches, publishes, accepts, or
merges a task.

## Presentation and redaction

MCP responses deliberately omit project `repo_path`, `worktree_root`,
`codex_command`, allowlisted argv, verification argv, raw task payloads, agent
commands, and artifact contents. Task views expose identifiers, status,
timestamps, canonical head, Draft PR URL, bounded criteria, bounded redacted
errors, verification summaries, review summaries, and recent redacted events.
All strings pass the Core redactor and are truncated to documented limits.

No tool returns environment variables, arbitrary files, arbitrary SQL, shell
output, verification artifact contents, or an unrestricted event history.

## Dispatcher

`project_brain_queue_dispatch_next` does not execute `TaskEngine` on the MCP
request thread. It performs read-only preflight checks:

1. reject when the Core runtime flock is held;
2. run a dry-run recovery/claim preview and reject live, ambiguous, or
   `recovery_blocked` claim blockers;
3. report `idle` when no task is claimable;
4. otherwise create a private dispatch log and start a detached fixed worker.

The worker command is derived only from the running installation and runtime:
the current Python executable runs `-m project_brain --runtime-root <fixed
runtime> apply --json`. Request input cannot change argv, cwd, environment, or
the runtime path. The child uses a fixed package working directory and a
minimal allowlisted environment inherited from server startup. Core's runtime
flock and transactional `claim_next()` remain the final concurrency gate.

Dispatch returns after `Popen`, with a redacted PID/log identifier and no wait
for implementation, verification, or publication. Logs live under the runtime
`logs/mcp-dispatch/` directory (`0700`), files are created as `0600`, and the
worker's bounded/redacted completion record is written by a fixed supervisor.
Each dispatch request records an append-only event, including blocked/idle
outcomes and an optional redacted reason.

## Recovery preview

The recovery tool invokes the same recovery classifier with `execute=False`.
It may show `would_recover`, `would_recovery_block`, or an unchanged live-state
reason, plus the current global claim blockers. It exposes no `execute`,
`terminate_agent`, `confirm_no_agent`, `resume`, `cancel`, cleanup, or deletion
input. Operator recovery remains CLI-only.

## Security invariants

- bind only to IP loopback and document Secure MCP Tunnel as the supported
  remote path;
- accept only explicit tool schemas and fixed Core operations;
- reject credential-like values and executable/path control fields deeply;
- redact and bound every response and dispatch log;
- keep runtime directories `0700` and files `0600`;
- audit every create, review, and dispatch write;
- never expose shell, filesystem, SQL, Git mutation, cleanup, recovery
  resolution, PR merge, or arbitrary worker configuration;
- preserve the registered main checkout and Core single-agent claim gate.

## Verification

Automated tests cover tool discovery and annotations, Streamable HTTP startup,
loopback rejection, all eight tool contracts, create idempotency, exact-head
review, recovery dry-run behavior, dispatcher busy/blocked/idle/start paths,
fixed worker parameters, private permissions, deep forbidden fields, secret
rejection, response redaction, and output bounds. Tests use temporary runtimes
and fake workers; they do not call ChatGPT, Secure MCP Tunnel, GitHub, Codex, or
the public internet.

Manual acceptance first uses an official MCP client or Inspector against
`http://127.0.0.1:7677/mcp`. Secure MCP Tunnel acceptance additionally requires
operator-owned Platform tunnel permissions, a runtime API key, and ChatGPT
developer-mode access. Lack of those external credentials must be reported as
an unverified manual step, never converted into an automated pass.

## Non-goals

This MVP does not provide OAuth, LAN/public binding, a public reverse proxy,
arbitrary shell/filesystem access, unrestricted recovery, cleanup, PR merge,
automatic acceptance, multi-agent scheduling, Gmail migration, UI resources,
prompts, sampling, or MCP Tasks protocol support.
