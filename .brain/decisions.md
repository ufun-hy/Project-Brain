# Decisions

## D-001: Project state belongs to the project

The durable context must live with the project rather than inside ChatGPT, Codex, Notion, Obsidian, or any single tool.

## D-002: GitHub is a synchronization carrier

GitHub is currently used to version and synchronize Project Brain files across computers. It is not Project Brain itself.

## D-003: Separate planning from execution

ChatGPT is used primarily for planning, clarification, and reasoning. Codex is used only when code execution or repository-level implementation is needed.

## D-004: Use a local Bridge for execution (legacy)

Because the ChatGPT GitHub connection is read-only, a local Bridge receives structured tasks through Gmail and performs controlled Git operations.
This records the original experiment; D-012 supersedes Gmail as a Core
architecture decision while leaving the live legacy implementation frozen.

## D-005: Keep the first state model minimal

The first context experiment used only `problem.md`, `current.md`, and
`decisions.md`. Those project-owned context files remain minimal. Bridge usage
subsequently proved the need for operational task/event persistence, which is
now owned by Core SQLite rather than added to the context documents.

## D-006: Do not execute arbitrary remote shell commands

Core may write files, invoke Codex in registered repositories, or run locally
allowlisted commands. It must not execute command or argv supplied by any
external source adapter.

## D-007: Separate runtime state from source

Configuration, SQLite state, worktrees, evidence artifacts, logs, OAuth tokens,
and other mutable runtime files live under an overridable
`~/.project-brain/`. Git contains only source, examples, documentation, and
tests.

## D-008: Use stable identities and SQLite events

Projects use stable `project_id` values and tasks use `task_id`, `dedupe_key`,
and revision. Transport-specific message IDs are source metadata only.
Transactional SQLite state and append-only events are the Core source of truth.

## D-009: Execute only in registered task worktrees

Core fetches the latest remote default branch and creates one worktree per task.
The registered main checkout may be dirty or on any branch and must never be
checked out, reset, cleaned, or used as the Codex working directory.

## D-010: Separate execution from review and acceptance

A successful execution records criterion-specific evidence and enters
`awaiting_review`. ChatGPT can review evidence, but the user controls acceptance
and merge authorization. Core does not automatically merge.

## D-011: Use one-shot locked execution

Manual and scheduled apply commands share a runtime `flock`. Each process
claims at most one task and exits so the next launch loads current code.

## D-012: Keep Core source-neutral and freeze the live Gmail Bridge

Core accepts canonical task envelopes and trusted verification IDs. The live
legacy Gmail Bridge remains unchanged and outside Core. Future MCP/DevSpace
transport work requires its own adapter decision and review.

## D-013: Model attempts by phase and bind review to commits

Implementation, verification, publication, and review are durable phases.
Review findings bind to a canonical SHA; `needs_changes` reruns implementation
and appends a new canonical commit, while publication-only failures resume
publication.

## D-014: Prefer deterministic recovery over implicit reclamation

Interrupted tasks are reconciled from runtime and Git evidence under the flock.
Only exact registered remote branches can reconstruct released worktrees.
Unsafe running state fails closed. Terminal worktrees are removed only after
their failure evidence is persisted in an immutable manifest-hashed archive;
archive or cleanup safety failure retains the worktree.

## D-015: Supervise agents and bind evidence to canonical state

Codex owns a persisted process group with birth/executable identity and
background heartbeats. Recovery re-verifies identity before every signal and
returns a global claim-safety report before scheduling. The engine never claims
the same or a different task while any task remains `running` or
`recovery_blocked`. Missing or ambiguous identity enters an operator-resolved
`recovery_blocked` state.
Verification results belong to append-only verification sets identified
independently from retry attempt counts and bound to one canonical commit.
Review verdicts are applied as one transaction against that same canonical
head.

## D-016: Human-owned local refs are detect-only

Repository seals may restore Core-owned remote-tracking metadata, but a changed
local default-branch ref blocks publication without restoration or deletion.
Bridge records and retains evidence instead of rewriting a branch owned by the
user’s primary checkout.

## D-017: MCP is a controlled Core adapter over a private tunnel

Project Brain exposes only allowlisted canonical task, status, dispatch,
review, and recovery-preview operations through MCP. It does not expose a
shell, arbitrary files, Git mutation, cleanup, recovery resolution, acceptance,
or merge. The no-auth Streamable HTTP listener is loopback-only. ChatGPT remote
access uses OpenAI Secure MCP Tunnel's outbound HTTPS path; Project Brain does
not provide or endorse a public unauthenticated endpoint. The long-running MCP
server starts fixed one-shot Core workers asynchronously, while RuntimeLock,
the global claim gate, and the existing state machine remain authoritative.
Dispatch is annotated as potentially destructive and open-world because the
worker may call Codex and GitHub. A daemon reaper waits for spawned workers and
audits bounded exit metadata without terminating safely running detached
processes. Supersession remains an atomic Store/state-machine operation: active
execution/recovery/merge ownership is protected, revisions increase strictly,
and terminal history is never rewritten. The adapter pins `mcp==1.28.1` until
its private generated-model hardening passes the documented upgrade gate.

## D-018: Bind every task to an immutable project execution snapshot

SQLite is authoritative for project configuration; JSON is explicit
bootstrap/import/export only. Execution-affecting project changes create a
monotonic revision and canonical SHA-256. Task creation atomically stores that
revision, hash, and full execution profile. All later execution, retry, review
revision, recovery, verification, publication, release, cleanup, and forensics
use the stored snapshot and fail closed if it is missing or changed. Display
name changes do not create an execution revision. MCP remains read/control only
and gains no configuration mutation tool.

## D-019: Make external acceptance an MCP-ingress authority

External acceptance is a durable Core schema-v7 state machine, not a UI flag or
operator declaration. One-time challenge plaintext is returned once and never
persisted; only its SHA-256 is stored. A run binds app/Core versions,
installation identity, Tunnel fingerprint, and expiry. Only the registered,
strict, no-side-effect MCP probe can consume a waiting challenge and write
`passed`; Core CLI and Swift expose no pass command. Historical pass remains
independent from current Tunnel health. Fixture and CI probes never represent
real ChatGPT external acceptance.

## D-020: Import reviewed Tunnel binaries; never silently download them

Product Shell opens the official Platform entry point but does not fetch or
execute arbitrary URLs. The user selects one regular executable. A static
bundled manifest allowlists reviewed version/platform/architecture/runtime-
contract combinations, beginning with Tunnel Client 0.0.10 arm64. The app uses
fixed `--version`, bounded output/time, Mach-O and SHA-256 validation, private
same-directory staging, fsync, atomic replacement, rollback, and fail-closed
removal after confirmed stop. User confirmation of official origin is shown as
such and is never mislabeled as cryptographic supply-chain verification.
