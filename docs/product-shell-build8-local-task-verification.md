# Product Shell Build 8 local-task verification

Version: `0.8.0 (8)`

Base: `main@7259acfa1c38e30f3f8c2126eb7c7c3f8c271e3f`

Branch: `codex/project-brain-local-task-intake-v1`

Delivery: new Draft PR

## Scope

Build 8 implements RFC-008 without adding a new runtime architecture. The
native App sends strict schema-v1 requests over stdin to fixed Core commands.
Core binds a reviewed `local-v1:` plan to the exact remote Base, registered
repository identity, project revision/hash, execution profile, delivery,
readiness, request hash, expiration, and single transactional consumption.

Analyze/Review completes with a persisted result when the worktree is unchanged
and cannot commit, push, or publish. Implement change retains the existing
isolated worktree, verification seal, canonical commit, bounded push/Draft PR,
review, retry, recovery, and forensic cleanup rules. Swift and Core share CLI
contract 1.1.0; App/Core are 0.8.0, database schema is 9, and result schema is 1.

## Repository verification

- Core request validation rejects unknown fields and all command/argv/cwd/
  environment/SQL/path/executable/branch/worktree/credential controls.
- Plan hashing, expiry, request/profile/Base/readiness changes, single use,
  repeated confirmation, and concurrent confirmation are covered.
- Analyze no-change completion, result persistence and unchanged main checkout
  are covered.
- Implement worktree isolation, result/commit evidence and no publication when
  delivery is tightened are covered.
- Schema v8 → v9 preservation, idempotence, SQL rollback, old/external task
  compatibility, and existing recovery tests are included in the full suite.
- Swift tests cover the shared contract, structured stdin, result/snapshot
  decoding, completed presentation, and one-time guide persistence. Source
  regressions cover menu/Task Center entry points, inline error recovery,
  localization, forbidden UI controls, and final artifact wiring.

Local verification on 2026-07-19 passed all 240 Python/Core tests, Swift package
compilation, Xcode project/localization plist validation, shell/Python script
syntax checks, and a PyInstaller build of Core 0.8.0 with CLI contract 1.1.0.
The 67 SwiftPM/Xcode test methods, final App build, launchd lifecycle, final-DMG
flow, and artifact hashes remain subject to the exact-head GitHub Actions run;
they must not be treated as passed before that run completes.

## Final artifact gate

CI produces only the distinct
`Project-Brain-Local-Tasks-Build8-arm64` artifact. Its schema-v3 manifest binds
the Git head, App executable, Core helper, CLI contract, App/Core versions,
request/result/database schema versions, artifact names, and SHA-256 values.

The final-DMG test runs only on an isolated macOS CI runner. It mounts Build 8,
copies the App to `/Applications`, and invokes the helper embedded in that App.
Under an isolated HOME it preserves an existing project and terminal task,
simulates a schema-v8 upgrade, verifies schema 9, starts the managed Worker,
submits a strict local Analyze request, observes Pending/Running/Completed,
checks the structured result after a new helper process, and proves the
registered main checkout remains byte-for-byte Git-clean. It does not use
ChatGPT, Tunnel credentials, Gmail, a source virtualenv helper, or a production
repository.

A real Implement Draft PR is deliberately not created by artifact CI because
RFC-008 requires an explicitly authorized disposable repository for that
external mutation.

## External status

External ChatGPT acceptance remains **Pending**. Local Core, launchd, UI,
transport, and DMG results are repository evidence only; none authenticates a
ChatGPT control-plane request. Build 8 is unsigned and not notarized.
