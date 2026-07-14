# Current State

Last updated: 2026-07-14

## Current stage

Project Brain Core MVP is implemented and locally verified on branch
`codex/project-brain-core-mvp`. It is awaiting review through a new Draft PR;
execution success is not treated as user acceptance.

## Active task

Review the Core MVP architecture, implementation, migration boundary, and
verification evidence against `docs/rfc/RFC-003-core-v3.md` and the Draft PR.

## Recently confirmed

- Mutable runtime state is separated under an overridable `~/.project-brain/`.
- SQLite persists projects, tasks, attempts, worktrees, agent sessions,
  verification evidence, and append-only events.
- Tasks execute only in isolated registered worktrees; dirty main checkouts do
  not block task creation and are not checked out, reset, or cleaned.
- Git result normalization covers uncommitted changes, one or more commits, and
  ordinary cherry-picks while rejecting branch switches, history rewrites, and
  unresolved conflicts.
- Gmail is a compatibility input adapter and one apply process executes at most
  one task under a shared flock.
- 67 Core tests and 3 Gmail compatibility-entry tests pass locally.
- Existing Draft PR #10 and PR #11 were not changed, closed, or merged.

## Blockers and uncertainties

No implementation blocker is known. Product acceptance and merge remain user
review decisions. Real Gmail, GitHub, and Codex credentials were intentionally
not used by automated tests.

## Next concrete starting point

Review the new Draft PR, inspect the per-criterion evidence and migration steps,
then either request a `needs_changes` revision or explicitly authorize merge.

## Scope limits

Core MVP does not add a menu bar product, web console, public MCP tunnel,
multi-agent execution, automatic merge, team permissions, billing, or a
template marketplace.

## Read next

- `docs/rfc/RFC-003-core-v3.md`
- `docs/core-v3-gap-analysis.md`
- `docs/migration-bridge-v2.md`
- `docs/troubleshooting-recovery.md`
- `README.md`
