# Current State

Last updated: 2026-07-14

## Current stage

The PR #12 review revision is implemented and locally validated on
`codex/project-brain-core-mvp`. The PR remains Draft for renewed review; PR #10
and PR #11 remain untouched.

## Implemented review changes

- Gmail productization was withdrawn from Core; the legacy experiment matches
  `origin/main` and remains frozen.
- Source-neutral canonical enqueue rejects external command/argv and resolves
  criteria only through trusted project verification IDs.
- SQLite schema v2 persists attempt phases, commit-bound reviews, and structured
  findings with atomic forward migration and future-version rejection.
- `needs_changes` reruns implementation with active findings and appends a new
  canonical commit. Publication-only transient failures resume publication.
- Startup and CLI recovery reconcile interrupted real processes using runtime,
  PID/heartbeat, worktree, Git, and remote evidence.
- Published review worktrees can be released and later rebuilt from an exact
  registered remote SHA while reusing the Draft PR.
- Strict ID/path constraints, private runtime permissions, origin verification,
  and a post-verification Git seal block unsafe publication.
- Reproducible Core validation and GitHub Actions CI were added.

## Verification status

The expanded 86-test Core suite passes locally through
`scripts/verify-core.sh`. Gmail legacy tests are not part of Core validation
because the legacy implementation is unchanged.

## Next concrete starting point

Inspect the updated Draft PR #12 and its CI result against the review closure
matrix. Do not treat implementation success as acceptance or merge
authorization.

## Scope limits

Core MVP does not add Gmail productization, an MCP/DevSpace adapter, a menu bar
product, web console, public tunnel, multi-agent execution, automatic merge,
team permissions, billing, or a template marketplace.

## Read next

- `docs/rfc/RFC-003-core-v3.md`
- `docs/core-v3-gap-analysis.md`
- `docs/troubleshooting-recovery.md`
- `README.md`
