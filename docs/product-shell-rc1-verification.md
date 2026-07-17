# Product Shell RC1 verification matrix

Exact stacked base:
`codex/project-brain-product-shell-v1@1475915a8c43681270c829ee96b4c4104659aa7a`.

## Repository-side gates

| Requirement | Evidence | Required result |
|---|---|---|
| Core regression | `scripts/verify-core.sh` | all Python tests pass |
| schema v6 → v7 | rollback, restart, idempotency, identity preservation tests | pass |
| acceptance challenge | hash-only persistence, expiry, mismatch, replay, concurrency, supersede, restart tests | pass |
| MCP-only completion | strict schema plus real Streamable HTTP dispatch test | pass; not external acceptance |
| controlled project task | plan-token binding and exact one-file verifier tests | pass |
| Tunnel importer | file kind, symlink, architecture, version, timeout, output, atomicity, rollback, permissions tests | pass |
| app acceptance presentation | blocking/pending/passed, auto-wait/cancel, restart, historical/current separation tests | pass |
| diagnostic privacy | no raw Tunnel ID, challenge, credential, or absolute user path | pass |
| frozen helper | exact 0.7.0 build and clean-environment init/status | pass |
| real launchd lifecycle | install, healthy, stop, start, healthy, uninstall, data preservation | pass |
| SwiftPM | all model/adapter/installer tests | pass |
| Xcode | committed project build/tests and embedded resource checks | pass |
| RC artifacts | Release app, arm64 DMG/ZIP, manifest and recomputed SHA-256 | pass |
| Gmail isolation | exact-base tracked diff under `experiments/gmail-inbox/` | empty |

The development host has Apple Command Line Tools but not the full Xcode
application. Local `ProjectBrainKit` and `ProjectBrainApp` SwiftPM builds are
valid compile checks; XCTest, Xcode app build, DMG creation, and artifact upload
must be taken from the Draft PR macOS Actions run.

The controlled fake Mach-O bytes used by installer unit tests are test fixtures,
not an official Tunnel Client. The Streamable HTTP probe in CI is a transport
regression, not a real ChatGPT ingress acceptance.

## External acceptance

| Item | Status | Why CI cannot close it |
|---|---|---|
| Install RC1 on user Mac | Pending | requires user Finder/Gatekeeper interaction |
| Import official Tunnel Client | Pending | requires user-confirmed official download |
| Configure Tunnel ID/key | Pending | requires real credentials |
| Tunnel control-plane ready | Pending | requires OpenAI control plane |
| ChatGPT tool discovery | Pending | requires user workspace/connector |
| Real acceptance probe ingress | Pending | requires ChatGPT → Tunnel → MCP path |
| Real-project Draft PR closure | Pending | requires explicit project selection and user review |
| Apple signing/notarization | Pending | requires release credentials and external services |

The Draft PR must remain Draft while these items are Pending. It must never be
described as a signed, notarized, publicly releasable build.
