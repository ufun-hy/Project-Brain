# Decisions

## D-001: Project state belongs to the project

Durable project context should live with the project rather than depend on one ChatGPT conversation, one Codex session, or one machine.

## D-002: ChatGPT plans and reviews; Codex executes

ChatGPT owns clarification, product and architecture decisions, task framing, and final review. Codex is used for repository-level implementation and required checks after the work is already decided.

## D-003: Project Brain is a thin execution bridge

The normal product flow is:

`ChatGPT -> MCP -> Project Brain -> isolated worktree -> Codex CLI -> checks -> ChatGPT review`

Project Brain should not recreate planning, review, or engineering-management features that already belong to ChatGPT or Codex.

## D-004: MCP is transport, not the Core

MCP is the preferred ChatGPT ingress. A Tunnel or MCP outage may make the local Core temporarily unreachable from ChatGPT, but it must not define the Core state model or make local execution data invalid.

The old Gmail Bridge remains only a historical simplicity reference; Gmail is not the target transport.

## D-005: Execute only in registered isolated worktrees

Project Brain knows a small set of registered repositories and creates a managed worktree for each execution. The user's main checkout is never the Codex working directory and must not be switched, reset, or cleaned by Project Brain.

## D-006: Use Codex CLI for bounded local implementation

Project Brain launches the configured Codex CLI in the task worktree and gives it the final implementation brief. Codex returns what changed, which files were touched, checks performed, results, and blockers.

Codex may run task-specific or project-default checks. Those checks are execution evidence for ChatGPT review, not a separate Project Brain acceptance system.

## D-007: Stop on failure

If Codex execution or required checks fail, the task stops and returns the code state and failure evidence. Project Brain does not automatically retry, enter `needs_changes`, or create a redispatch lifecycle. A repair happens only after a new explicit user decision in ChatGPT.

## D-008: Normal tasks stay local

Project Brain does not automatically commit, push, create Draft PRs, publish, merge, or manage exact-head review states for normal work. The user decides when a larger body of local work is ready to commit or integrate.

## D-009: Keep task state minimal

The initial simplified task model should stay close to `queued`, `running`, `completed`, and `failed`, plus only the runtime metadata required for safe execution and recovery from process interruption.

Internal identifiers, process metadata, worktree paths, dedupe protections, and similar safety details may exist, but they must not become normal user workflow steps.

## D-010: Personal use first; no App requirement

Project Brain is currently a personal/internal tool. A macOS App, Task Center, local New Task UI, onboarding wizard, signing, notarization, auto-update, and public distribution are deferred until real usage creates a need.

## D-011: Start the Simplified Core with fresh runtime data

Old Project Brain task history, Build state, review/publication state, acceptance records, and recovery attempts have no migration requirement. The simplified Core may use a fresh runtime and a new minimal SQLite schema.

## D-012: Reuse proven early components, not the old state machine

The early Core/MCP code around `12251944c3dfa66ae49032c8710c4a9d142f59a9` is a useful implementation source for MCP, isolated worktrees, Codex subprocess execution, and SQLite persistence.

Do not restore its publication, verification-set, review, retry, merge, forensic, or canonical-commit lifecycle wholesale. Reuse only the parts that directly serve the thin-bridge flow.

## D-013: Add complexity only from observed need

Do not add a new abstraction, UI, lifecycle state, acceptance mechanism, or automation simply because it is architecturally possible. Add it only when repeated real use shows that the simpler flow is insufficient.

## D-014: Ponytail is a Codex execution policy, not Core state

Project Brain may select an optional Ponytail mode for Codex to encourage reuse, native capabilities, and minimal correct diffs. The default is `lite`; stronger `full` or `ultra` modes are explicit execution choices rather than new task lifecycle states, and `off` disables the policy for that task.

Project Brain does not vendor Ponytail, make Ponytail review an acceptance authority, or let it override repository instructions, explicit acceptance criteria, validation, security, accessibility, required tests, or product contracts.

The integration stays a thin Codex execution policy: set `PONYTAIL_DEFAULT_MODE` on the child process and explicitly prefix the Codex task with `@ponytail <mode>`. The explicit prompt activation is required because verified Codex 0.149.0 sessions received the environment variable without reliably activating Ponytail through SessionStart. This remains removable or changeable without migrating Project Brain state.
