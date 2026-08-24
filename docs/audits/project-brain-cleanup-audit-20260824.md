# Project-Brain cleanup audit — 2026-08-24

## Scope and safety boundary

This is a read-only audit of the Project-Brain Git repositories and their explicitly related worktrees:

- Canonical checkout: /Users/ufun/code/2026/Project-Brain
- Protected Gmail worktree: /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2
- Current audit checkout: /Users/ufun/code/2026/Project-Brain-gmail-tasks
- Three Git-reported stale worktree paths under /Users/ufun/.project-brain-simplified/worktrees/project-brain/

No other product repository was inspected. No cleanup command was executed. In particular, this audit did not delete, reset, clean, stash, merge, rebase, checkout, switch, prune, remove, push, or otherwise rewrite a branch or worktree. The primary dirty checkout and protected Gmail worktree were preserved exactly as observed.

Credential and runtime file contents were never read. Only filenames, Git status, ignore rules, and directory existence were checked for the named Gmail artifacts.

## Executive findings

1. The canonical repository is on main at 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca, exactly equal to its local origin/main tracking ref and 0/0 ahead/behind.
2. The primary main checkout is intentionally dirty: 30 tracked files are modified and 5 files are untracked. All 30 tracked changes are unstaged; there are no staged changes. The tracked diff is +1191/-54.
3. Exactly five of the 30 tracked dirty paths overlap paths changed by origin/feature/ponytail-policy; no untracked path overlaps that branch. This is path overlap only; no content equivalence was asserted.
4. The protected Gmail worktree is clean, detached, and exactly at 3417dec4bf046cd73219cf7457a3d7b9007fa30a. The local remote-tracking ref origin/restore/gmail-bridge-v2 is the same SHA, and that SHA is an ancestor of main.
5. origin/feature/ponytail-policy is not merged into main: it is 11 commits ahead of main and main is 1 commit ahead of it, with merge base 23fb9370fbcecc1bd8630b2dbc7cef548f33147c. Its head is reachable only from that remote-tracking branch in the canonical clone.
6. Three local brain/task-* branches point exactly at main and have no unique commits, but their linked worktree directories are missing and Git reports their worktree records as prunable. They are candidates for later SAFE_REMOVE_WORKTREE followed by SAFE_DELETE_LOCAL, subject to a separately authorized cleanup task.
7. git fsck --full --no-reflogs --unreachable found 51 unreachable commit objects. They are not reachable from any retained branch and require NEEDS_DECISION; none was touched.
8. The operating system denied both ps and pgrep process-list access, so active process state could not be determined. This is explicitly reported as unknown rather than interpreted as “no process running.”
9. Live remote and GitHub PR verification was unavailable: SSH access to github.com was denied by the environment and gh could not connect to api.github.com. Local commit metadata associates the protected restore commit with PR #7 via its subject, but live PR state was not independently confirmed.
10. No item qualifies for SAFE_DELETE_REMOTE. The restore branch is explicitly protected, and the feature branch contains unmerged commits that overlap the dirty primary checkout.

## Repository and checkout identity

| Checkout | Git root | Git common directory | HEAD | Working state | Classification |
|---|---|---|---|---|---|
| /Users/ufun/code/2026/Project-Brain | same path | .git | main → 9b5b64b | 30 tracked modifications, 5 untracked files | KEEP_DIRTY |
| /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 | same path | /Users/ufun/code/2026/Project-Brain/.git | detached 3417dec4 | clean; protected runtime worktree | KEEP_ACTIVE |
| /Users/ufun/code/2026/Project-Brain-gmail-tasks | same path | .git | brain/codex-52fe81918d → 9b5b64b | clean audit checkout; standalone clone | KEEP_ACTIVE |

The canonical remote is:

    origin git@github.com:ufun-hy/Project-Brain.git

The protected Gmail worktree shares the canonical repository’s Git common directory. The current audit checkout is a separate clone with its own local branch database; it is not a linked worktree of the canonical clone.

## Branch inventory and divergence

For git rev-list --left-right --count main...REF, the first number is commits only in main and the second is commits only in REF.

| Ref | SHA | Ahead/behind relative to main | Worktree / reachability evidence | Classification |
|---|---|---:|---|---|
| main | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Checked out by the dirty primary checkout; retained trunk | KEEP_DIRTY |
| brain/task-5589abe30aef4764 | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Associated path is missing; tip fully reachable from main | SAFE_DELETE_LOCAL after stale worktree metadata is removed |
| brain/task-b69bdc2d54e64403 | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Associated path is missing; tip fully reachable from main | SAFE_DELETE_LOCAL after stale worktree metadata is removed |
| brain/task-f8c81fe8600a4887 | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Associated path is missing; tip fully reachable from main | SAFE_DELETE_LOCAL after stale worktree metadata is removed |
| origin/main | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Same tip as main; default remote branch | KEEP_ACTIVE |
| origin/restore/gmail-bridge-v2 | 3417dec4bf046cd73219cf7457a3d7b9007fa30a | 43 / 0 | Explicitly protected; ancestor of main; active detached Gmail worktree uses this SHA | KEEP_ACTIVE |
| origin/feature/ponytail-policy | 56e8c8ff18c9ea34e1189e03a910f4df7e562985 | 1 / 11 | Only canonical ref containing its head; not merged into main | KEEP_UNMERGED |
| origin/HEAD | symbolic ref → origin/main | n/a | Default-branch symbolic ref | KEEP_ACTIVE |
| brain/codex-52fe81918d in audit clone | 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca | 0 / 0 | Current audit worktree; no unique commits | KEEP_ACTIVE |

The canonical origin/HEAD symbolic ref resolves to refs/remotes/origin/main.

The live remote branch list could not be refreshed. The table identifies remote branches from existing local remote-tracking refs; the local origin/restore/gmail-bridge-v2 SHA is exactly the user-protected SHA, but a current server-side SHA was not independently verified.

## Worktree inventory

The canonical git worktree list --porcelain reported:

| Worktree path | HEAD | State | Classification |
|---|---|---|---|
| /Users/ufun/code/2026/Project-Brain | 9b5b64b on main | Dirty; 30 tracked + 5 untracked | KEEP_DIRTY |
| /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 | detached 3417dec4 | Clean and explicitly protected | KEEP_ACTIVE |
| /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-5589abe30aef4764 | 9b5b64b on brain/task-5589abe30aef4764 | prunable gitdir file points to non-existent location; directory missing | SAFE_REMOVE_WORKTREE later |
| /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-b69bdc2d54e64403 | 9b5b64b on brain/task-b69bdc2d54e64403 | prunable gitdir file points to non-existent location; directory missing | SAFE_REMOVE_WORKTREE later |
| /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-f8c81fe8600a4887 | 9b5b64b on brain/task-f8c81fe8600a4887 | prunable gitdir file points to non-existent location; directory missing | SAFE_REMOVE_WORKTREE later |

The audit checkout /Users/ufun/code/2026/Project-Brain-gmail-tasks is a separate clone and consequently does not appear in the canonical clone’s git worktree list.

## Dirty primary checkout: complete path inventory

The primary checkout is main at 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca, with origin/main and no ahead/behind difference. The 30 tracked paths below are all unstaged modifications relative to that commit and are therefore local worktree state, not branch-reachable commits.

### 30 tracked modified paths — KEEP_DIRTY

    README.md
    apps/macos/ProjectBrain/ProjectBrain/AppModel.swift
    apps/macos/ProjectBrain/ProjectBrain/ConnectionCenterView.swift
    apps/macos/ProjectBrain/ProjectBrain/OnboardingView.swift
    apps/macos/ProjectBrain/ProjectBrain/ProjectBrainApp.swift
    apps/macos/ProjectBrain/ProjectBrainKit/CoreClient.swift
    apps/macos/ProjectBrain/ProjectBrainKit/CoreCommand.swift
    apps/macos/ProjectBrain/ProjectBrainKit/CoreModels.swift
    apps/macos/ProjectBrain/ProjectBrainKit/Diagnostics.swift
    apps/macos/ProjectBrain/ProjectBrainKit/TunnelClient.swift
    apps/macos/ProjectBrain/ProjectBrainTests/OnboardingDiagnosticsTests.swift
    apps/macos/ProjectBrain/ProjectBrainTests/TunnelClientTests.swift
    docs/mcp-adapter.md
    docs/product-shell.md
    packaging/pyinstaller/project-brain.spec
    pyproject.toml
    src/project_brain/cli.py
    src/project_brain/models.py
    src/project_brain/readiness.py
    src/project_brain/schema.py
    src/project_brain/services.py
    src/project_brain/store.py
    src/project_brain_simplified/gitops.py
    src/project_brain_simplified/service.py
    src/project_brain_simplified/worker.py
    tests/test_product_shell_integration.py
    tests/test_readiness.py
    tests/test_services.py
    tests/test_simplified_core.py
    tests/test_store.py

The tracked diff summary is 30 files changed, 1,191 insertions, and 54 deletions. There are no staged changes.

### 5 untracked paths — KEEP_DIRTY

    config/mail.example.json
    docs/mail-adapter.md
    scripts/verify-formal-mcp-artifact.py
    src/project_brain/mail.py
    tests/test_mail.py

These five files are also local-only worktree state. They were not compared by content with any branch.

## Dirty-primary overlap with feature/ponytail-policy

The feature branch’s full tree delta against current main is 20 paths, +219/-1834, because the feature branch is based at the older merge base 23fb937 while current main contains the later simplified-core commit. The exact intersection between dirty tracked paths and the feature branch’s changed paths is:

    pyproject.toml
    src/project_brain_simplified/gitops.py
    src/project_brain_simplified/service.py
    src/project_brain_simplified/worker.py
    tests/test_simplified_core.py

There is no intersection between the five untracked paths and the feature branch’s changed paths.

This overlap is material. The dirty primary changes touch the simplified-core files that the feature branch’s tree delta removes or otherwise changes relative to main. The dirty state must therefore be preserved before any branch or worktree operation. No cleanup disposition is safe for the five overlapping files.

## Commit reachability and unique commits

### Protected restore line

Evidence:

    merge-base(main, origin/restore/gmail-bridge-v2) = 3417dec4bf046cd73219cf7457a3d7b9007fa30a
    origin/restore/gmail-bridge-v2 is an ancestor of main: yes
    main is an ancestor of origin/restore/gmail-bridge-v2: no
    commits in main after restore: 43
    commits in restore absent from main: 0

Therefore, the protected restore commit is reachable from main and also retained by its explicit remote-tracking branch. The detached Gmail worktree is pinned to the same SHA. This is KEEP_ACTIVE, not a deletion candidate.

### Unique feature commits

The following 11 commits are reachable from origin/feature/ponytail-policy but not from main or origin/restore/gmail-bridge-v2:

    56e8c8ff18c9ea34e1189e03a910f4df7e562985 docs: clarify ponytail activation decision
    a3a4f5bea26b2801fcc3c0890292f47515a4d7fc docs: record deterministic ponytail activation contract
    f3e76a1a20200f349f598a16b24f4ca651905ab5 test: assert Codex prompt activates ponytail
    7739984c3307dd7ab7c516b2e4e96ca3bc60dbba test: cover explicit ponytail prompt activation
    ce440e419df6a77cfef1fa5ac8b92355724fb6dd fix: activate ponytail before Codex task body
    a3dd62e90a14f51f15807f5963cf0578226d97a7 fix: explicitly activate ponytail in Codex prompts
    537c210eaa3fd2a409d8d79a60133e2debb0fec6 docs: record Ponytail execution policy decision
    a9a8e1f1e4e6063427b76cf7aae0f70d73724a96 docs: define Ponytail integration policy
    ff480bda8b4332b52b4394a2fd92e5182f952dbf feat: pass Ponytail mode to Codex
    762b2deae4a9cf5676f16b6c3e39e4c7bbf87728 test: cover Ponytail mode resolution
    b064cfd38bf86bc314dd45f1768b4a00c3c66b23 feat: add Ponytail execution policy adapter

git branch -a --contains 56e8c8ff18c9ea34e1189e03a910f4df7e562985 returned only remotes/origin/feature/ponytail-policy in the canonical clone. These commits are KEEP_UNMERGED; deleting the remote branch would discard the only named branch containing them.

### Main-only history relative to the feature branch

Current main has one commit not in the feature branch:

    9b5b64b03df77b2fff20aa11bdb80a8056bad7ca feat: adopt simplified Project Brain core

This is the main tip shared by origin/main and all three brain/task-* local branches.

### Unreachable commits

git fsck --full --no-reflogs --unreachable found 51 unreachable commits. None is reachable from main, origin/main, origin/restore/gmail-bridge-v2, origin/feature/ponytail-policy, or the local task branches. They are all NEEDS_DECISION; no reflog expiry, prune, or object deletion was performed.

Only commit IDs, timestamps, and subjects were read; no unreachable blob or tree contents were read.

    f2c087dc05376c749201e5644c79e3952e346945 2026-07-16T20:04:28+08:00 build: package managed core helper
    13c1a5c798108962800d6e066c6c99dc4ba377f7 2026-07-16T06:28:56+08:00 fix: close MCP adapter review findings
    92c34aab41356a450aba515a3e9c0934d9ae3d7d 2026-07-16T20:46:03+08:00 ci: fetch product shell isolation baseline
    f70737d2c15d8aa0d10a92087e7b871e35cac005 2026-07-16T13:37:56+08:00 feat: add project config snapshots
    a488c5aac9ed511df3df2e10b808c0e24572605f 2026-07-12T10:14:32+08:00 feat: initialize minimal project brain state
    e8885e3cc7aa9646b71cef0e132b4b99a0364cd2 2026-07-18T00:43:55+08:00 fix: render transport terminal status titles
    3c09becde27de1fc0972d29d1aadd9b206e92064 2026-07-16T15:57:32+08:00 fix: harden project configuration onboarding
    5d0bf00e00d475bda8035770fac2c198b0b2b942 2026-07-18T01:17:37+08:00 build: advance RC artifact to build 4
    aacbea920eb71e81993b26a9d5c21f0d23f593cd 2026-07-12T16:18:33+08:00 docs: add Project Brain validation RFC
    48ccd0614243604d12cdde608d685f56a5573658 2026-07-16T22:15:34+08:00 fix: close Product Shell review findings
    ecced501c860af69ee480a6aef5b4730c38ae6a2 2026-07-15T05:01:09+08:00 fix: close PR 12 review blockers
    7b8f969e24eff7460d47446f382a26413c35d57f 2026-07-12T00:06:13+08:00 feat: initialize Project Brain bridge
    2dd1d44b9dc869e7fda753a4769d576d2eb8a72d 2026-07-12T00:10:58+08:00 docs: verify project brain bridge v2
    f9130a0be1c81cdc4c806e6ef496ceb293c98bad 2026-08-15T23:34:07+08:00 fix prepublication verification retry
    1d95ff186ee4a99c0c92d384fd9c2e556421e4b5 2026-07-12T00:12:40+08:00 fix: normalize Gmail task JSON
    22d6741bf47e2de203307e85aae2305cafdd263f 2026-07-16T20:37:23+08:00 test: verify product shell integration
    0bd9404c5a2a94ed5eaa94793edeae7f2e4953ab 2026-07-15T14:59:49+08:00 docs: record v5 claim gate verification
    2ad9c6f9399fb4d6cecdfdc33a806a7320583dc5 2026-08-10T13:24:26+08:00 feat: complete pb-pr19-web-e2e-implement-20260809-01
    89d91e13a6f3a8b4226586f616475552016afd38 2026-07-12T16:50:11+08:00 fix: return bridge repository to base branch
    801a6ca23cfa17684712b9176a5b3a76aeb56fce 2026-07-17T17:34:13+08:00 ci: bind RC artifacts to exact PR head
    fe1aaa303b1051fcb1610807adf5a9dd083f1356 2026-07-12T00:18:10+08:00 docs: add RFC-001 for the local bridge
    6d1b79fc9927bd8756c092f83b60cf46c9f8f8c2 2026-07-14T17:27:10+08:00 test: make Git fixtures portable across CI
    b8dbf8be772ea97790c684dbe689be74522a1a79 2026-07-18T00:43:55+08:00 fix: render transport terminal status titles
    cb9b84e8418bc8a4b4835b99f8e380c6e953a505 2026-07-12T16:04:35+08:00 docs: add RFC for Project Brain validation
    46dd1198001ac1ffb234924f7723b806e9cb5661 2026-07-16T20:25:48+08:00 feat: add native macOS product shell
    9c1e20af319d1d0e2bd0bbf3fce9645087b493f4 2026-07-18T00:06:53+08:00 fix: close RC1 acceptance and installer review gaps
    e59ffceb0f06389547862dc93f378f03fbf52ec7 2026-08-10T14:40:41+08:00 docs: record AC evidence for web e2e
    452083e9ac6f37a66655d316e2eff4e38a6ce712 2026-07-12T16:47:40+08:00 fix: harden bridge cleanup and retry behavior
    cce019542f1bbdf28fe077619099ad4524daff06 2026-07-15T10:14:29+08:00 docs: record v4 verification state
    f22081fee4d4751e9bac2d1cc8c98ee0a884e56c 2026-07-15T18:25:44+08:00 feat: add controlled MCP adapter
    5867a53c472a6f8a07b721a5e6041d4ca5e0c3c5 2026-08-21T12:30:17+08:00 feat: adopt simplified Project Brain core
    122b1c7e36ebfefa7d63406d5ed1596dbd4eb9ab 2026-08-09T23:14:20+08:00 feat: complete pb-pr19-web-e2e-implement-20260809-01
    15eb90ab3cc1cabdacb6cd266a0970000254c10b 2026-07-16T19:55:17+08:00 feat: add product service lifecycle
    68abf4aaaa2d08d3890ff65c60b239961992e896 2026-07-15T10:13:00+08:00 fix: close core recovery safety review
    d42bdcc7f81816c35e761fec8346e7ffded863bc 2026-07-16T19:55:17+08:00 feat: add product service lifecycle
    f0ec1d678fb9ed37618432b69ec1687f4161dafe 2026-07-17T17:29:39+08:00 feat: ship zero-CLI Product Shell RC1
    4fadb8bc2e5d33593b60d62aa609a5793735aa64 2026-07-14T17:24:57+08:00 fix: address Core MVP architecture review
    abaefa3fe3ce927d242673b05a472c0d82f44125 2026-07-14T16:24:20+08:00 feat: implement Project Brain Core MVP
    e3ae0a166a42650cd93a6aeae66f4e9f772d73b0 2026-07-17T15:09:04+08:00 fix: fail closed when removing tunnel configuration
    a23102e7bb3847206d87a9025b848ea669959611 2026-08-10T14:42:08+08:00 docs: record final Draft state evidence
    bb32377e04cea5fde5a00b01bb08413d2908046a 2026-07-12T16:48:38+08:00 chore: register kefu-ai pilot project
    af349c03f2fa8f9dd166a7a062c10f5c080940b9 2026-07-16T20:43:40+08:00 ci: target Xcode 15 project format
    1475915a8c43681270c829ee96b4c4104659aa7a 2026-07-17T15:14:11+08:00 docs: record tunnel removal verification
    f5b6923ea82f54ff62994d314475643829faf2c4 2026-07-12T18:30:20+08:00 feat: add observable task status and macOS menu bar
    d27932d450ab8d163ba93b2e9c1f512481873c29 2026-07-17T17:29:39+08:00 feat: ship zero-CLI Product Shell RC1
    983a10bf0482256ec3273ad7e103273068e06b69 2026-07-17T17:34:13+08:00 ci: bind RC artifacts to exact PR head
    fe3a7e392e7005897e2db3e256b0dbce975ff9d7 2026-07-15T11:27:09+08:00 fix: gate claims during agent recovery
    9abba68fd3331ddd33e051e68bcf5af80a5f863d 2026-07-18T00:06:53+08:00 fix: close RC1 acceptance and installer review gaps
    70bcd0b3b56fa92f44127a5229002ed0101e4a41 2026-07-12T20:26:08+08:00 fix: complete observable task audit loop
    5ebd3ecaff646524a6cda2cd26899e82a149ba55 2026-07-16T13:37:56+08:00 feat: add project config snapshots
    edff47f2b3c60c5b770e7e093946dd8900aeecd6 2026-07-16T15:57:32+08:00 fix: harden project configuration onboarding

The repeated subjects and the 2026-08-21 unreachable commit with a simplified-core subject are reasons not to discard these objects automatically. They may be superseded or duplicate work, but that requires a separate content-level decision.

## PR associations

### Locally evidenced associations

- 3417dec4bf046cd73219cf7457a3d7b9007fa30a has subject “fix: harden Project Brain Bridge task recovery (#7)”. This is local evidence associating origin/restore/gmail-bridge-v2 with PR #7.
- The reachable main history contains local merge/subject references for PRs #23, #22, #21, #19, #18, #17, and earlier subject references for #16, #15, #14, #13, #12, #7, #6, #3, #2, and #1.
- None of the 11 unique feature/ponytail-policy subject lines contains a PR number. No local PR ref was present for it.

### Live verification limits

The following read-only live checks failed because of environment network restrictions:

- git ls-remote --symref origin HEAD and git ls-remote --heads origin: SSH connection to ssh.github.com:443 was not permitted.
- gh pr list, gh pr view 7, and GitHub’s commit-to-PR API query: unable to connect to api.github.com.

Accordingly, current server-side PR open/closed state and current server-side branch tips remain unverified. The local evidence is sufficient to preserve the restore branch and to classify the feature branch as KEEP_UNMERGED, but not to claim a current live PR state.

## Protected Gmail artifacts and runtime evidence

The following named paths were found under the active Gmail worktree and are ignored by experiments/gmail-inbox/.gitignore:

    experiments/gmail-inbox/credentials.json
    experiments/gmail-inbox/token.json
    experiments/gmail-inbox/bridge-config.json
    experiments/gmail-inbox/processed.json
    experiments/gmail-inbox/failures.json
    experiments/gmail-inbox/results/

The active Gmail worktree is clean (## HEAD (no branch)) and these files are ignored rather than tracked. They are KEEP_ACTIVE. No contents, sizes, or token values were read.

A filename-only scan outside .venv found the results/ directory but no filenames matching invalid, oauth, backup, archive, runtime, or evidence. This is only a negative filename-filter result; it is not evidence that the user-mentioned invalid OAuth backups or archived runtime evidence do not exist under another name or outside the scan’s naming patterns. They remain protected and were not touched; any disposition is NEEDS_DECISION until their exact paths are supplied or separately verified.

## Active process state

Process inspection was attempted only with repository/Gmail-specific filters. Both mechanisms were blocked by the environment:

    ps: zsh:1: operation not permitted: ps
    pgrep: Cannot get process list

Therefore, no conclusion about active Project-Brain or Gmail bridge processes can be made. Process state is NEEDS_DECISION for any later worktree operation. The audit did not stop or signal any process.

## Classification matrix

| Item | Classification | Reason / prerequisite |
|---|---|---|
| Dirty primary main checkout | KEEP_DIRTY | Explicitly protected; 30 tracked modifications and 5 untracked files are local-only worktree state |
| Each of the 30 tracked primary modifications | KEEP_DIRTY | Must not be reset, stashed, cleaned, or overwritten; five overlap the unmerged feature path set |
| Each of the 5 untracked primary files | KEEP_DIRTY | Local-only files; no content comparison or deletion authorized |
| main / origin/main | KEEP_ACTIVE | Retained trunk and current baseline; primary checkout is dirty |
| Active Gmail worktree | KEEP_ACTIVE | Explicitly protected; clean detached worktree at the protected SHA |
| origin/restore/gmail-bridge-v2 | KEEP_ACTIVE | Explicitly protected at 3417dec4bf046cd73219cf7457a3d7b9007fa30a; locally reachable from main |
| Gmail credentials, token, bridge config, state files, and results/ | KEEP_ACTIVE | Explicitly protected runtime evidence; ignored and present; contents not read |
| origin/feature/ponytail-policy | KEEP_UNMERGED | 11 unique commits; only named branch containing its head; dirty primary overlaps five changed paths |
| Three stale task worktree records/paths | SAFE_REMOVE_WORKTREE later | Git says prunable and filesystem directories are missing; run a later dry-run and obtain separate authorization first |
| Three brain/task-* local branches | SAFE_DELETE_LOCAL later | All point at main, 0 unique commits; delete only after stale worktree metadata is removed and rechecked |
| Current audit checkout and brain/codex-52fe81918d | KEEP_ACTIVE | Current worktree producing this report; no unique commits |
| 51 unreachable commits | NEEDS_DECISION | Not reachable from any retained branch; repeated/superseded-looking work may still be valuable |
| Live remote SHA/PR state | NEEDS_DECISION | Network/API access unavailable; local remote-tracking refs are evidence but may be stale |
| Any remote branch deletion | No SAFE_DELETE_REMOTE candidate | Restore is protected; feature is unmerged; no remote deletion is authorized by this audit |

## Proposed cleanup order for a later separately authorized task

No command in this section was executed. The order is intentionally conservative:

1. Preserve and independently snapshot/verify the dirty primary checkout, the active Gmail worktree, the protected runtime artifacts, and the origin/restore/gmail-bridge-v2 SHA. Resolve the 51 unreachable commits and the feature branch’s 11 unique commits before deleting any ref.
2. Re-check the live remote and PR state in an environment with GitHub access. Do not delete origin/feature/ponytail-policy until its 11 commits and the five dirty-path overlaps have an explicit disposition.
3. Confirm that no process is using the stale worktree paths. Then run the read-only preview:

       git -C /Users/ufun/code/2026/Project-Brain worktree prune --dry-run

4. Only after separate authorization, remove only the three confirmed stale worktree administrative records:

       git -C /Users/ufun/code/2026/Project-Brain worktree prune

5. Re-run git worktree list --porcelain, branch status, and reachability checks. Only if the three task branches are no longer registered as checked out, delete them with the non-force, merged-only form:

       git -C /Users/ufun/code/2026/Project-Brain branch -d brain/task-5589abe30aef4764
       git -C /Users/ufun/code/2026/Project-Brain branch -d brain/task-b69bdc2d54e64403
       git -C /Users/ufun/code/2026/Project-Brain branch -d brain/task-f8c81fe8600a4887

6. Do not run any remote deletion command in the proposed cleanup. In particular, do not delete restore/gmail-bridge-v2, do not delete feature/ponytail-policy without a decision, and do not alter the dirty primary checkout or active Gmail worktree.

Commands explicitly out of scope remain out of scope: git reset, git clean, git stash, git merge, git rebase, git checkout, git switch, force branch deletion, remote branch deletion, and any deletion of credentials, tokens, runtime state, results, OAuth backups, or archived evidence.

## Exact commands executed

All commands below were read-only except the requested report-directory creation and report write. Commands that failed did not modify Git state.

### Checkout identity and status

    pwd
    git rev-parse --show-toplevel
    git rev-parse --git-common-dir
    git rev-parse --is-inside-work-tree
    git worktree list --porcelain
    git branch -a -vv
    git remote -v
    git status --short --branch
    git show-ref --heads --remotes

The same identity/status checks were run with explicit git -C paths against /Users/ufun/code/2026/Project-Brain, /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2, and /Users/ufun/code/2026/Project-Brain-gmail-tasks, including:

    git -C PATH rev-parse --show-toplevel
    git -C PATH rev-parse --git-common-dir
    git -C PATH symbolic-ref --short -q HEAD || git -C PATH rev-parse --short HEAD
    git -C PATH rev-parse HEAD
    git -C PATH status --short --branch
    git -C PATH diff --stat
    git -C PATH diff --name-status
    git -C PATH ls-files --others --exclude-standard
    git -C PATH worktree list --porcelain

### Branches, refs, divergence, and reachability

    git -C /Users/ufun/code/2026/Project-Brain branch -a -vv
    git -C /Users/ufun/code/2026/Project-Brain for-each-ref --format='%(refname) %(objectname) %(symref) %(upstream:short) %(upstream:track) %(authordate:iso8601) %(subject)' refs/heads refs/remotes/origin
    git -C /Users/ufun/code/2026/Project-Brain show-ref --heads
    git -C /Users/ufun/code/2026/Project-Brain symbolic-ref refs/remotes/origin/HEAD
    git -C /Users/ufun/code/2026/Project-Brain log --all --graph --decorate --oneline --date-order -30
    git -C /Users/ufun/code/2026/Project-Brain log --format='%H%n%P%n%ad%n%an%n%s%n' --date=iso-strict --all --max-count=30
    git -C /Users/ufun/code/2026/Project-Brain rev-list --left-right --count main...origin/restore/gmail-bridge-v2
    git -C /Users/ufun/code/2026/Project-Brain rev-list --left-right --count main...origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain diff --name-status main origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain diff --stat main origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain show --stat --summary --decorate --format=fuller origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain show --stat --summary --decorate --format=fuller origin/restore/gmail-bridge-v2
    git -C /Users/ufun/code/2026/Project-Brain merge-base --is-ancestor origin/restore/gmail-bridge-v2 main
    git -C /Users/ufun/code/2026/Project-Brain merge-base --is-ancestor main origin/restore/gmail-bridge-v2
    git -C /Users/ufun/code/2026/Project-Brain merge-base main origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain log --format='%H %s' main..origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain log --format='%H %s' origin/feature/ponytail-policy..main
    git -C /Users/ufun/code/2026/Project-Brain log --format='%H %s' origin/restore/gmail-bridge-v2..main
    git -C /Users/ufun/code/2026/Project-Brain log --format='%H %s' main..origin/restore/gmail-bridge-v2
    git -C /Users/ufun/code/2026/Project-Brain rev-list --count main..origin/feature/ponytail-policy
    git -C /Users/ufun/code/2026/Project-Brain rev-list --count origin/feature/ponytail-policy..main
    git -C /Users/ufun/code/2026/Project-Brain rev-list --count origin/restore/gmail-bridge-v2..main
    git -C /Users/ufun/code/2026/Project-Brain rev-list --all --not main origin/restore/gmail-bridge-v2 --count
    git -C /Users/ufun/code/2026/Project-Brain rev-list --all --not main origin/restore/gmail-bridge-v2 --format='%H %s'
    git -C /Users/ufun/code/2026/Project-Brain branch -a --contains 3417dec4bf046cd73219cf7457a3d7b9007fa30a
    git -C /Users/ufun/code/2026/Project-Brain branch -a --contains 56e8c8ff18c9ea34e1189e03a910f4df7e562985
    git -C /Users/ufun/code/2026/Project-Brain branch -a --contains 9b5b64b03df77b2fff20aa11bdb80a8056bad7ca
    git -C /Users/ufun/code/2026/Project-Brain fsck --full --no-reflogs --unreachable
    git -C /Users/ufun/code/2026/Project-Brain log --all --format='%H %s' --grep='#[0-9]' -50

The all-ref ahead/behind loop was:

    git for-each-ref --format='%(refname:short)' refs/heads refs/remotes/origin | while IFS= read -r ref; do case "$ref" in origin|origin/HEAD) continue;; esac; counts=$(git rev-list --left-right --count main..."$ref"); printf '%-45s %s\n' "$ref" "$counts"; done

The dirty-path overlap command was:

    zsh -c 'tracked=$(git diff --name-only main | sort); untracked=$(git ls-files --others --exclude-standard | sort); feature=$(git diff --name-only main origin/feature/ponytail-policy | sort); printf "TRACKED_DIRTY_COUNT "; printf "%s\n" "$tracked" | awk "NF" | wc -l; printf "UNTRACKED_COUNT "; printf "%s\n" "$untracked" | awk "NF" | wc -l; printf "PATH_OVERLAP_WITH_FEATURE\n"; comm -12 <(printf "%s\n" "$tracked") <(printf "%s\n" "$feature"); printf "UNTRACKED_OVERLAP_WITH_FEATURE\n"; comm -12 <(printf "%s\n" "$untracked") <(printf "%s\n" "$feature")'

### Dirty state and protected files

    git -C /Users/ufun/code/2026/Project-Brain diff --name-only main
    git -C /Users/ufun/code/2026/Project-Brain ls-files --others --exclude-standard
    git -C /Users/ufun/code/2026/Project-Brain diff --cached --name-status
    git -C /Users/ufun/code/2026/Project-Brain diff --cached --stat
    git -C /Users/ufun/code/2026/Project-Brain status --porcelain=v2 --branch
    git -C /Users/ufun/code/2026/Project-Brain diff --stat main
    git -C /Users/ufun/code/2026/Project-Brain diff --numstat main
    git -C /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 status --short --branch --untracked-files=all
    git -C /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 check-ignore -v --no-index experiments/gmail-inbox/credentials.json experiments/gmail-inbox/token.json experiments/gmail-inbox/bridge-config.json experiments/gmail-inbox/processed.json experiments/gmail-inbox/failures.json experiments/gmail-inbox/results
    git -C /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 status --ignored --short --untracked-files=all
    find /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 -maxdepth 5 \( -name credentials.json -o -name token.json -o -name bridge-config.json -o -name processed.json -o -name failures.json -o -name results -o -iname '*oauth*' -o -iname '*archive*' -o -iname '*runtime*' \) -print
    find /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2/experiments/gmail-inbox -maxdepth 5 -type f -print
    find /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 -path '*/.venv' -prune -o -type f -print
    find /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 -path '*/.venv' -prune -o -type d -print

### Worktree paths and process checks

    git -C /Users/ufun/code/2026/Project-Brain worktree list --porcelain
    for p in /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-5589abe30aef4764 /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-b69bdc2d54e64403 /Users/ufun/.project-brain-simplified/worktrees/project-brain/task-f8c81fe8600a4887; do if test -d "$p"; then printf 'DIRECTORY_EXISTS %s\n' "$p"; if test -e "$p/.git"; then printf 'GIT_METADATA_EXISTS %s/.git\n' "$p"; sed -n '1,3p' "$p/.git"; else printf 'GIT_METADATA_MISSING %s/.git\n' "$p"; fi; else printf 'DIRECTORY_MISSING %s\n' "$p"; fi; done
    for p in /Users/ufun/code/2026/Project-Brain /Users/ufun/code/2026/Project-Brain-gmail-bridge-v2 /Users/ufun/code/2026/Project-Brain-gmail-tasks; do if test -d "$p"; then printf 'DIRECTORY_EXISTS %s\n' "$p"; else printf 'DIRECTORY_MISSING %s\n' "$p"; fi; done
    ps -axo pid=,ppid=,etime=,state=,comm=,args= | rg -i '(/Users/ufun/code/2026/Project-Brain|Project-Brain-gmail-bridge-v2|project_brain|bridge_v2|gmail-inbox)' || true
    command -v pgrep || true
    pgrep -af 'Project-Brain|project_brain|bridge_v2|gmail-inbox' 2>&1 || true

### Remote and PR checks

    git -C /Users/ufun/code/2026/Project-Brain ls-remote --symref origin HEAD
    git -C /Users/ufun/code/2026/Project-Brain ls-remote --heads origin
    command -v gh || true
    gh pr list --repo ufun-hy/Project-Brain --state all --limit 100 --json number,title,state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit,closedAt,url
    gh pr list --repo ufun-hy/Project-Brain --state all --head restore/gmail-bridge-v2 --json number,title,state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit,closedAt,url
    gh pr list --repo ufun-hy/Project-Brain --state all --head feature/ponytail-policy --json number,title,state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit,closedAt,url
    gh pr view 7 --repo ufun-hy/Project-Brain --json number,title,state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit,closedAt,url
    gh api repos/ufun-hy/Project-Brain/commits/3417dec4bf046cd73219cf7457a3d7b9007fa30a/pulls --jq '.[] | {number,title,state,head:.head.ref,base:.base.ref,url}'

### Non-mutating probes that failed harmlessly

These exact probes returned errors but did not alter repository state:

    git show-ref --heads --remotes
    git -C /Users/ufun/code/2026/Project-Brain show-ref --remotes
    git -C /Users/ufun/code/2026/Project-Brain gh pr list --repo ufun-hy/Project-Brain --state all --limit 100 --json number,title,state,isDraft,headRefName,baseRefName,headRefOid,mergeCommit,closedAt,url
    git -C /Users/ufun/code/2026/Project-Brain git status --short --branch
    git -C /Users/ufun/code/2026/Project-Brain sh -c '...'
    sh -c '...process-substitution overlap probe...'

The first two used an unsupported git show-ref option, the next two were invalid command prefixes, and the shell probes were rejected by the selected shell. Corrected native-shell commands are included above and supplied the report’s evidence.

The requested report directory did not exist, so the only filesystem creation performed was:

    mkdir -p docs/audits

    The report itself was then created at docs/audits/project-brain-cleanup-audit-20260824.md.
