# Project-Brain stale local cleanup — blocked

Date: 2026-08-24

Status: **Blocked; no stale records or local branches were successfully removed.**

Scope was limited to `/Users/ufun/code/2026/Project-Brain` and its explicitly protected Gmail worktree `/Users/ufun/code/2026/Project-Brain-gmail-bridge-v2`. No other product repository was inspected, modified, or cleaned. Credential and token contents were not read or printed.

## Safety gate and cleanup result

The before gate passed:

- Main checkout was on `main` at `9b5b64b03df77b2fff20aa11bdb80a8056bad7ca`.
- All three authorized filesystem paths were absent.
- Each authorized branch existed at exactly `9b5b64b03df77b2fff20aa11bdb80a8056bad7ca` and had `0` commits not reachable from `main`.
- The dry-run reported exactly the three authorized stale records and no other record.

Exact `git worktree prune --dry-run` output:

```text
Removing worktrees/task-5589abe30aef4764: gitdir file points to non-existent location
Removing worktrees/task-b69bdc2d54e64403: gitdir file points to non-existent location
Removing worktrees/task-f8c81fe8600a4887: gitdir file points to non-existent location
```

The required command was then run:

```text
git -C /Users/ufun/code/2026/Project-Brain worktree prune
```

It failed to remove all three records. Exact stderr:

```text
error: failed to delete '.git/worktrees/task-5589abe30aef4764': Operation not permitted
error: failed to delete '.git/worktrees/task-b69bdc2d54e64403': Operation not permitted
error: failed to delete '.git/worktrees/task-f8c81fe8600a4887': Operation not permitted
```

Post-prune verification showed all three stale records still present. Therefore no branch deletion was attempted. Exact local branches successfully deleted: **none**. No force deletion was used.

## Protected primary checkout invariants

The following hashes are SHA-256 hashes of the exact command outputs. The status and untracked hashes use NUL-delimited output.

| Evidence | Before | After | Result |
|---|---|---|---|
| Branch | `main` | `main` | unchanged |
| HEAD | `9b5b64b03df77b2fff20aa11bdb80a8056bad7ca` | `9b5b64b03df77b2fff20aa11bdb80a8056bad7ca` | unchanged |
| `status --porcelain=v1 -z --untracked-files=all` | `27a38ebf4145aa19c4d937957b5f5d2b39b585de7cb9b0056a6279578c432b67` | `27a38ebf4145aa19c4d937957b5f5d2b39b585de7cb9b0056a6279578c432b67` | unchanged |
| Untracked path list | `a4138f281a87e45231683b1e83609723868771cee79c8c0f7157b22e5570588c` | `a4138f281a87e45231683b1e83609723868771cee79c8c0f7157b22e5570588c` | unchanged |
| Unstaged `git diff --binary` | `e411655f92b11f91c97ec43cfba5839ba0a29b88a1c04c797044ebb8d42cf1cf` | `e411655f92b11f91c97ec43cfba5839ba0a29b88a1c04c797044ebb8d42cf1cf` | unchanged |
| Staged `git diff --cached --binary` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | unchanged; empty |

Staged status path list was empty before and after. The exact tracked modified path list was unchanged:

```text
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
```

The exact untracked path list was unchanged before and after:

```text
config/mail.example.json
docs/mail-adapter.md
scripts/verify-formal-mcp-artifact.py
src/project_brain/mail.py
tests/test_mail.py
```

## Authorized branches and worktrees

Before and after, each branch remained at the required tip with zero commits beyond `main`:

```text
brain/task-5589abe30aef4764  9b5b64b03df77b2fff20aa11bdb80a8056bad7ca  unreachable_from_main=0
brain/task-b69bdc2d54e64403  9b5b64b03df77b2fff20aa11bdb80a8056bad7ca  unreachable_from_main=0
brain/task-f8c81fe8600a4887  9b5b64b03df77b2fff20aa11bdb80a8056bad7ca  unreachable_from_main=0
```

The three filesystem paths remained absent. The stale administrative records remained listed because the prune operation was denied.

## Protected Gmail worktree and runtime

- `/Users/ufun/code/2026/Project-Brain-gmail-bridge-v2` remained detached at `3417dec4bf046cd73219cf7457a3d7b9007fa30a`.
- Its tracked status was empty before and after; the empty NUL-delimited status hash was `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` in both snapshots.
- The worktree remained present in the canonical worktree list.
- LaunchAgent `com.projectbrain.gmail-bridge` remained loaded and running with active count `1`, using `/Users/ufun/Library/LaunchAgents/com.projectbrain.gmail-bridge.plist`.
- A names-and-filesystem-metadata-only snapshot of the protected Gmail runtime files, result records, archived/evidence paths, logs, and LaunchAgent plist was unchanged: `84518137eaa8977eebe75208ba4f4f66576d1f299d8a8bbbffe5fb5a1cedeb06` before and after. Contents were not read or printed.

## Refs and repository scope

- Remote refs changed: **none**. The complete `refs/remotes/origin` snapshot hash was `352a1b9ba39806e54607c620f9131458e9cd31484adab423c01bcb226fdb2a7e` before and after.
- Product repositories changed: **none**. No product source file, checkout state, remote ref, Gmail runtime file, credential, token, or LaunchAgent was changed.
- Partial completion: the exact prune command was attempted, but Git could not delete any of the three stale administrative records. The three authorized local branches remain intact for a later retry in an environment permitted to modify the canonical repository's `.git/worktrees` metadata.

## Evidence-file persistence

The report was created at this requested path in the writable task workspace. Staging it with `git add -- docs/audits/project-brain-stale-local-cleanup-20260824.md` was attempted but denied because the workspace Git index lock could not be created (`.git/index.lock: Operation not permitted`). The report therefore remains the sole new untracked file; no other task-workspace file was changed.
