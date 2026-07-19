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

## D-019: Make external acceptance an MCP-ingress authority (superseded)

External acceptance is a durable Core schema-v7 state machine, not a UI flag or
operator declaration. One-time challenge plaintext is returned once and never
persisted; only its SHA-256 is stored. A run binds app/Core versions,
installation identity, Tunnel fingerprint, and expiry. Only the registered,
strict, no-side-effect MCP probe can consume a waiting challenge and write
`passed`; Core CLI and Swift expose no pass command. Historical pass remains
independent from current Tunnel health. Fixture and CI probes never represent
real ChatGPT external acceptance. D-021 supersedes the authority conclusion:
loopback MCP ingress is not source-authenticated.

## D-020: Import reviewed Tunnel binaries; never silently download them

Product Shell opens the official Platform entry point but does not fetch or
execute arbitrary URLs. The user selects one regular executable. A static
bundled manifest allowlists reviewed version/platform/architecture/runtime-
contract combinations, beginning with Tunnel Client 0.0.10 arm64. The app uses
fixed `--version`, bounded output/time, Mach-O and SHA-256 validation, private
same-directory staging, fsync, atomic replacement, rollback, and fail-closed
removal after confirmed stop. User confirmation of official origin is shown as
such and is never mislabeled as cryptographic supply-chain verification.

## D-021: Keep MCP transport evidence distinct from ChatGPT authority

The Secure MCP Tunnel contract currently supplies no signed request attestation,
mTLS identity, or other source signal that a loopback client cannot forge.
Therefore schema v8 migrates legacy `passed` rows and records challenge
completion only as `mcp_transport_probe_passed` with unattributed ingress.
`external_chatgpt_verified` remains Pending, and the future real-project task
fails closed. Historical evidence is applicable to the current transport only
when installation, app, Core, Tunnel fingerprint, acceptance contract, and
readiness all match; applicability still does not elevate it to ChatGPT proof.

Tunnel selection is zero-execution static preflight. Fixed `--version` requires
explicit user authorization. Installation additionally proves the reviewed
read-only `runtimes list --json` contract under an isolated temporary HOME while
the old binary is still available for rollback; invalid contracts remove fresh
installs or restore the previous SHA.

## D-022: Resolve onboarding identity before mutation and require Applications

Native onboarding uses a dedicated Core mode that compares canonical repository
real path and normalized origin before stable ID and case-folded display-name
owners. A matching registration keeps its authoritative ID and name and yields
`use_existing` or an execution-profile `update`; it never becomes a duplicate
`add`. ID, name, and path collisions are structured plan errors. Apply repeats
resolution under RuntimeLock, and SQLite retains the final transactional name,
path, revision, hash, and action checks. The ordinary CLI add contract remains
strict unless the native onboarding flag is explicitly supplied.

An app bundle is formally installed only at
`/Applications/Project Brain.app`. DMG and other locations remain usable for
exploration but cannot complete local readiness or onboarding. Build 5 uses
distinct artifact names and supersedes immutable Build 4 without overwriting it.

## D-023: Make installation and process lifecycle explicit

The Release app declares `LSMultipleInstancesProhibited` so Launch Services
rejects a second instance even when a user opens different bundle copies. The
final generated `Info.plist` is authoritative; packaging and mounted-artifact
verification assert its Boolean value rather than trusting only project source.

Quitting is a first-class user action in both the menu-bar panel and Settings.
It terminates the app process without deleting or resetting services, projects,
tasks, Keychain values, or runtime data.

The internal RC DMG contains `Project Brain.app`, an `Applications` symlink to
`/Applications`, and a bilingual file whose name and contents instruct the user
to drag the app onto that folder. CI mounts the completed image and validates
the visible install components. Build 6 supersedes immutable Builds 4 and 5
using new artifact names; it never overwrites either historical build.

## D-024: Treat the native App as a source-neutral, review-first task ingress

The macOS App sends only a strict schema-v1 local task document over stdin to
fixed Core commands. Goal and criteria are content, never command, argv, cwd,
environment, path, SQL, executable, branch, worktree, credential, or sandbox
authority. Core, not Swift, creates task/dedupe identities and binds the exact
remote Base, project revision/hash, execution profile, delivery policy,
readiness, expiry, and single-use plan token in SQLite schema v9.

Analyze and Implement share the authoritative task engine and isolated
worktrees. Analyze runs read-only, treats no changes as success, persists a
structured result, and never publishes. Implement keeps canonical commit,
verification seal, optional bounded push/Draft PR, review, recovery, and
cleanup rules. ChatGPT, Secure MCP Tunnel, and Gmail are optional or separate
ingresses; local success never changes external ChatGPT acceptance from
Pending.
