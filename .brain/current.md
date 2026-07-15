# Current State

Last updated: 2026-07-16

## Current stage

Core 0.3.0 is merged. RFC-004 MCP Adapter MVP and the F1-F4 review closure are
implemented in the independent `codex/project-brain-mcp-adapter` worktree for
Draft PR #13. PR #10 and PR #11 remain untouched.

## Implemented MCP adapter

- The verified official MCP Python SDK release (`mcp==1.28.1`) provides
  Streamable HTTP at `/mcp`; the no-auth server binds only to `127.0.0.1` or
  `::1` and documents OpenAI Secure MCP Tunnel as the remote path.
- Eight strict-schema tools expose only health, registered projects, canonical
  Codex task intake, fixed asynchronous dispatch, bounded task state/evidence,
  exact-head atomic review, and read-only recovery preview.
- Unknown fields, bounded-string violations, credential-like input, and deeply
  nested executable/path controls fail before persistence. Responses omit raw
  payloads, commands, local paths, environments, and artifact contents.
- Dispatch never executes Codex on the MCP request thread. It checks the
  runtime lock and a read-only recovery/claim preview, then starts one fixed
  `python -m project_brain ... apply --json` worker with private JSON Lines
  logs. Core's RuntimeLock, claim gate, recovery, and one-task-per-process
  behavior remain authoritative.
- Supersession validation is atomic with task creation. Revisions must increase
  strictly; active execution, recovery, and merge ownership cannot be hidden;
  terminal history remains unchanged; and only state-machine-authorized old
  states transition to `superseded`.
- Dispatch is separately annotated as potentially destructive and open-world.
  A daemon reaper actively waits for each spawned worker, clears only that
  process under the dispatcher lock, and records a bounded/redacted exit event.
- The SDK is exactly pinned to the verified `mcp==1.28.1` because strict
  top-level unknown-field rejection uses compatibility-tested private argument
  model metadata.
- Create, review, and dispatch writes are auditable. MCP exposes no recovery
  resolution, cleanup, acceptance, or merge action.

## Preserved Core guarantees

- Gmail productization was withdrawn from Core; the legacy experiment matches
  `origin/main` and remains frozen.
- Source-neutral canonical enqueue rejects external command/argv and resolves
  criteria only through trusted project verification IDs.
- SQLite schema v4 persists supervised child process groups and birth/executable
  identity, canonical-head verification sets, atomic review verdicts, and
  forensic archives with atomic forward migration/backfill and future-version
  rejection.
- `needs_changes` reruns implementation with active findings and appends a new
  canonical commit. Publication-only transient failures resume publication.
- Startup and CLI recovery persist Codex PID/PGID plus process identity,
  maintain background heartbeats, verify identity before every signal, and use
  an auditable `recovery_blocked` state for missing/ambiguous identities.
- Recovery exposes a global claim-safety report, and startup does not claim any
  pending task while another task remains `running` or `recovery_blocked`.
- Terminal worktrees are cleaned only after private manifest-hashed failure
  evidence is persisted; archive or safety failure retains the worktree.
- Published review worktrees can be released and later rebuilt from an exact
  registered remote SHA while reusing the Draft PR.
- Strict ID/path constraints, private runtime permissions, origin verification,
  local/remote default-ref sealing, and exact Draft PR identity checks block
  unsafe publication. The human-owned local default ref is detect-only and is
  never rewound or deleted.
- Reproducible Core validation and GitHub Actions CI were added.

## Verification status

The full 139-test gate passes under Python 3.11 with `mcp==1.28.1`. This
includes the original 131-test MCP delivery gate plus eight review-closure
tests for supersession ownership/atomicity/revisions/terminal history, MCP
state conflicts and claim blockers, dispatch annotations, SDK compatibility,
and automatic worker reaping/exit audit. The real Streamable HTTP initialize,
tools/list, health call, and clean-shutdown test also passes. GitHub Actions
must remain green for every pushed PR head.

## Next concrete starting point

Keep Draft PR #13 unmerged for independent review. Secure MCP Tunnel and
ChatGPT acceptance require operator-owned Platform/workspace permissions and
must not be claimed from local tests alone.

## Scope limits

The MCP MVP does not add Gmail productization, arbitrary DevSpace file/terminal
authority, a menu bar product, web console, OAuth/RBAC, a public tunnel,
multi-agent execution, automatic merge, team billing, or a template marketplace.

## Read next

- `docs/rfc/RFC-003-core-v3.md`
- `docs/rfc/RFC-004-mcp-adapter.md`
- `docs/mcp-adapter.md`
- `docs/core-v3-gap-analysis.md`
- `docs/troubleshooting-recovery.md`
- `README.md`
