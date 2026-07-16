# Product Shell v1 verification matrix

Task base: `origin/main` at
`7dcf1f8c59937d2195ae75404ab7b4e4801c5c31`.

## Repository-side matrix

| Requirement | Evidence | Status |
|---|---|---|
| Core/service regression | `PYTHON_BIN=... bash scripts/verify-core.sh` | Local pass, 186 tests |
| Fixture product lifecycle | temporary runtime, bare remote, fake launchd boundary, real Core task/write/commit/reopen/uninstall | Local pass |
| Managed helper packaging | PyInstaller onefile; `--version`, clean-env `init`, and `status` | Local pass |
| Swift adapter/model tests | 25 cases: helper rollback, JSON models, typed argv, plan token, tunnel lifecycle/failures, observation/cancel/backoff, onboarding restore, redaction | macOS CI required |
| SwiftUI compile | `swift build --package-path apps/macos/ProjectBrain --product ProjectBrainApp` | Local pass |
| `Project Brain.app` build | committed Xcode project with embedded generated helper | macOS CI required |
| App without user venv | CI runs frozen helper through `env -i` and embeds it into app resources | macOS CI required |
| Config plan/apply | deterministic plan token; lock-time recompute; transaction-bound current/next assertions; add/update/concurrency tests | Local pass |
| Product readiness | Core + project checks + Worker/MCP + MCP initialize + `gh auth status`; failure regressions | Local pass |
| Service idempotency/data preservation | exact `gui/<uid>/<label>` bootout, strict fakes, rollback/retry, preservation tests | Local pass |
| Real macOS launchd lifecycle | frozen helper install → healthy → stop → start → healthy → uninstall, with runtime marker preservation | macOS CI required |
| Tunnel adapter | fixed official runtime argv/environment; invalid token/id, interruption, reconnect, and derived readiness tests | macOS CI required |
| Automatic observation | immediate/selected-detail refresh, non-overlap, cancellation, foreground/background/offline/backoff tests | macOS CI required |
| Helper upgrade rollback | atomic replacement plus failed activation rollback/reactivation test | macOS CI required |
| Secret isolation | Keychain store and redacted diagnostic export tests | macOS CI required |
| Gmail legacy isolation | CI diff from task base restricted to `experiments/gmail-inbox/` | macOS CI required |
| Main checkout isolation | recorded immediately before final delivery | Pending final evidence |
| PR #10/#11 isolation | GitHub head/state captured immediately before final delivery | Pending final evidence |

The local host has Apple Command Line Tools but not the full Xcode application,
so XCTest execution and `.app` build are deliberately not marked complete from
local SwiftPM compilation alone.

## External acceptance

| Acceptance | Status |
|---|---|
| Secure MCP Tunnel | Pending |
| ChatGPT developer mode | Pending |
| Real-project Product Shell flow | Pending |

No local, fixture, or CI result changes these three external statuses.
