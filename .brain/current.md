# Current State

Last updated: 2026-08-18

## Current direction

Project Brain is being simplified back to a thin personal bridge between ChatGPT and local Codex execution.

The target flow is:

`ChatGPT -> MCP -> Project Brain -> isolated worktree -> Codex CLI -> checks -> ChatGPT review`

ChatGPT handles discussion, analysis, decisions, task framing, and final review. Project Brain only has to locate the registered project, create an isolated worktree, run Codex, run the required checks, persist minimal task state, and return the result.

## Product boundary

The simplified Core should initially support only:

- registered projects;
- MCP ingress for ChatGPT;
- isolated Git worktrees;
- Codex CLI execution;
- simple persisted task state such as `queued`, `running`, `completed`, and `failed`;
- changed files / diff, Codex summary, test output, and blockers;
- safe process/runtime handling needed to avoid duplicate or destructive execution.

Normal tasks do not need Analyze tasks, draft/confirm flows, plan hashes, Project Brain review verdicts, automatic retries, canonical publication commits, push, Draft PR creation, merge handling, or a macOS App.

## Failure behavior

Codex completes the requested implementation and runs the required checks. If a check or execution fails, the task stops. The code changes and failure evidence remain available for ChatGPT review. A later repair is a new explicit user-approved execution, not an automatic retry lifecycle.

## Git behavior

Project Brain works only in its managed task worktree. It does not modify the user's main checkout. Normal task completion does not automatically commit, push, open a pull request, or merge. The user decides when a larger body of work is ready to commit or integrate.

## Runtime and history

The existing Project Brain runtime, database, Build history, old task records, review/publication state, and prior recovery attempts have no migration requirement for the simplified Core. A fresh runtime/database may start from a new minimal schema.

The old Gmail Bridge is useful as a simplicity reference but is not the desired transport. The early MCP/Core code around `12251944c3dfa66ae49032c8710c4a9d142f59a9` is a useful source for MCP, worktree, Codex subprocess, and SQLite pieces, but its verification/publication/review state machine should not be restored wholesale.

## Deferred

- macOS Product Shell and Task Center;
- local New Task UI;
- onboarding wizard and Tunnel installer UI;
- Developer ID signing, notarization, Sparkle, and public distribution;
- Analyze -> Implement workflow;
- confirmation token / plan hash flow;
- automatic Draft PR / publication lifecycle;
- exact-head Project Brain review / `needs_changes` / redispatch;
- automatic retry;
- `team-mode` integration for Codex.

## Next step

Build a clean Simplified Core from the smallest reusable early components, with a fresh runtime and a minimal end-to-end acceptance target: one ChatGPT request starts Codex in the correct isolated worktree and returns code changes plus test results for ChatGPT review.
