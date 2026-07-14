# Current State

Last updated: 2026-07-15

## Current stage

The PR #12 v3 and independent-review revision is implemented on
`codex/project-brain-core-mvp`. The PR remains Draft for renewed review; PR #10
and PR #11 remain untouched.

## Implemented review changes

- Gmail productization was withdrawn from Core; the legacy experiment matches
  `origin/main` and remains frozen.
- Source-neutral canonical enqueue rejects external command/argv and resolves
  criteria only through trusted project verification IDs.
- SQLite schema v3 persists supervised child process groups, canonical-head
  verification sets, atomic review verdicts, and forensic archives with atomic
  forward migration/backfill and future-version rejection.
- `needs_changes` reruns implementation with active findings and appends a new
  canonical commit. Publication-only transient failures resume publication.
- Startup and CLI recovery persist Codex PID/PGID, maintain background
  heartbeats, prevent concurrent attempts while a child group lives, and offer
  explicit whole-group termination.
- Terminal worktrees are cleaned only after private manifest-hashed failure
  evidence is persisted; archive or safety failure retains the worktree.
- Published review worktrees can be released and later rebuilt from an exact
  registered remote SHA while reusing the Draft PR.
- Strict ID/path constraints, private runtime permissions, origin verification,
  local/remote default-ref sealing, and exact Draft PR identity checks block
  unsafe publication.
- Reproducible Core validation and GitHub Actions CI were added.

## Verification status

The expanded 96-test Core suite passes locally through
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
