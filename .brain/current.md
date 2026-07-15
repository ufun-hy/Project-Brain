# Current State

Last updated: 2026-07-15

## Current stage

The PR #12 v5 claim-gate revision is implemented on
`codex/project-brain-core-mvp`. The PR remains Draft for renewed independent
review; PR #10 and PR #11 remain untouched.

## Implemented review changes

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

The expanded 109-test Core suite passes locally through
`scripts/verify-core.sh` and in GitHub Actions. Gmail legacy tests are not part
of Core validation because the legacy implementation is unchanged.

## Next concrete starting point

Inspect the updated Draft PR #12 and successful final CI result against the v5
review closure matrix. Do not treat implementation success as acceptance or
merge authorization.

## Scope limits

Core MVP does not add Gmail productization, an MCP/DevSpace adapter, a menu bar
product, web console, public tunnel, multi-agent execution, automatic merge,
team permissions, billing, or a template marketplace.

## Read next

- `docs/rfc/RFC-003-core-v3.md`
- `docs/core-v3-gap-analysis.md`
- `docs/troubleshooting-recovery.md`
- `README.md`
