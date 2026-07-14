# Project Brain Core v3 review closure matrix

Updated: 2026-07-14
Review input: `Project-Brain-Core-MVP-PR12-Review-v2.md`

| Review area | Implemented boundary | Regression evidence |
| --- | --- | --- |
| External validation commands | Canonical criteria contain text plus optional trusted `verification_id`; `command`/`argv` are rejected | `test_ingress`, `test_engine` |
| `needs_changes` execution | Durable attempt phases rerun Codex and append a canonical commit; only publication resumes publication | `test_review_lifecycle`, `test_engine` |
| Structured feedback | Reviews/findings bind verdict, severity, file, evidence, requirement to canonical `head_sha` and enter the next Codex prompt | `test_review_lifecycle` |
| Crash recovery | Startup and CLI reconcile PID, heartbeat, phase, worktree, Git and remote state | `test_recovery` including a terminated real process |
| Remote worktree/PR recovery | Exact registered remote SHA and ancestry are required; local worktree can be released and rebuilt; Draft PR is reused | `test_remote_recovery`, `test_github` |
| ID and path containment | Strict stable IDs, managed runtime roots, resolved containment, symlink rejection | `test_ingress`, `test_security`, `test_worktrees` |
| Worktree ownership | Project worktrees are confined to `<runtime>/worktrees/<project-id>/` | `test_projects`, `test_worktrees` |
| Verification mutation | A Git seal blocks file, commit, branch, origin, fetch/default-ref and conflict mutations before push | `test_repository_seal` |
| Gmail scope | Core Gmail module/tests/migration were removed; legacy `experiments/gmail-inbox/` matches `origin/main` | Git diff check plus Core-only validation |
| Migrations and permissions | Atomic schema v2 migration, future-schema rejection, `0700` dirs and `0600` state/artifacts | `test_migrations`, `test_security` |
| Dirty main checkout | Worktree creation, mutation blocking, remote recovery, and cleanup preserve main state | `test_worktrees`, `test_repository_seal`, `test_remote_recovery` |

The existing Gmail Bridge, PR #10, and PR #11 remain outside this change.
