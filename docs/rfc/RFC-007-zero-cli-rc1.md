# RFC-007: Zero-CLI Product Shell RC1

Status: Repository implementation complete; external acceptance pending
Target: Project Brain 0.7.0 build 1
Platform: macOS 14+, Apple Silicon arm64

## Decision

Project Brain RC1 makes the native app the complete operator surface for
installation, Tunnel setup, external acceptance, and the optional controlled
real-project acceptance task. An ordinary user does not need to run Core,
`tunnel-client`, `launchctl`, or Git commands.

The RC1 artifact is an unsigned, unnotarized internal release candidate. It is
not a production distribution. CI produces an arm64 DMG and ZIP, a machine-
verifiable build manifest, SHA-256 values, and a seven-day Actions artifact.
The official Tunnel Client is neither committed nor bundled.

## Managed Tunnel Client boundary

The app opens only the official OpenAI Platform Tunnels entry point and lets
the user select exactly one local file with `NSOpenPanel`. Selection is not
supply-chain proof: when no official machine-verifiable digest is available,
the confirmation screen says that the user must confirm the official source.

The installer accepts a regular, non-symlink executable containing the reviewed
arm64 Mach-O architecture. It executes only `<candidate> --version`, with a
five-second timeout, bounded concurrent stdout/stderr drains, a minimal
environment, strict semantic-version parsing, and redacted errors. Version
`0.0.10` is the only RC1 entry in the bundled schema-v1 compatibility manifest;
higher versions are rejected until the manifest and fixed-argv regressions are
reviewed.

Installation uses a private same-directory candidate, mode 0755, file fsync,
atomic rename, and directory fsync at:

```text
~/Library/Application Support/Project Brain/bin/tunnel-client
```

The managed path is the first discovery candidate. An upgrade retains the
previous validated binary until post-activation validation succeeds and rolls
back on failure. Removal validates the managed file and fails closed unless
the controlled runtime stop response proves `stopped` with no running process.
The installer does not remove quarantine attributes or invoke Gatekeeper
bypasses.

## External acceptance authority

Schema v7 adds a stable per-installation UUID plus acceptance runs and
append-only events. A challenge contains 256 bits of system randomness, expires
after ten minutes, is single-use, and is returned to the app once. SQLite stores
only its SHA-256. Each run binds Core and app versions, the installation
identity, the current Tunnel ID fingerprint, creation time, and expiry.

The states are `not_started`, `challenge_ready`, `waiting_for_chatgpt`,
`passed`, `failed`, `expired`, and `superseded`. A new run supersedes unfinished
runs. Expiry and ingress completion use immediate SQLite transactions;
conditional mutation permits exactly one concurrent winner. A historical pass
remains visible independently of current connection health.

Only the registered MCP tool `project_brain_acceptance_probe` reaches the
private completion operation. Its strict input schema contains one string field,
`challenge`, and rejects extra properties. It cannot accept command, argv,
environment, SQL, paths, or URLs; it does not execute processes, modify Git,
create tasks, or access arbitrary files. The response contains only probe
status, Project Brain version, verification time, and run ID. Core exposes no
`acceptance pass` CLI command, and the Swift typed-command enum exposes no pass
case. UserDefaults is explicitly non-authoritative; app restart restores status
only from Core schema-v7 state.

Transport tests exercise the real Streamable HTTP initialize/list/call path,
but are CI evidence only. They are not recorded as real ChatGPT external
acceptance.

## Controlled real-project acceptance task

After a historical external pass, the app may preview one fixed task for a
user-selected registered project that is accepting tasks and configured for
push plus Draft PR. The plan token binds the passed run and exact project
configuration revision/hash. The task uses the existing isolated worktree,
Codex, immutable verification set, publication, and Draft PR pipeline.

The only permitted changed path is:

```text
docs/project-brain-acceptance.md
```

Its exact content contains only acceptance time, Project Brain version, and run
ID. The dedicated verifier binds base/head SHA, requires exactly that one
regular non-symlink file, and compares exact UTF-8 content. No automatic merge,
default-checkout mutation, or cleanup outside existing safe ownership rules is
introduced.

## Artifact and credential boundary

`scripts/build-rc-artifact.sh` builds the Release app with signing disabled,
verifies the embedded Core helper and compatibility manifest, proves no Tunnel
Client is bundled, and produces DMG/ZIP artifacts. `build-manifest.json` binds
app version/build, Git head, Core version/hash, manifest version, supported
Tunnel version, architecture, signing/notarization status, Actions run URL, and
artifact hashes. `scripts/verify-rc-artifact.py` recomputes hashes and rejects
unexpected classification or external-acceptance claims.

Runtime API keys remain Keychain-only and enter the fixed Tunnel subprocess
environment. Raw Tunnel IDs are replaced by SHA-256 fingerprints in diagnostic
exports. Challenge plaintext is absent from SQLite, events, diagnostics, task
data, and build artifacts.

## External completion boundary

The following require real credentials and user actions and remain Pending:

- install the RC1 artifact on the user's Mac;
- import the official Tunnel Client;
- configure a real Tunnel ID and Runtime API key;
- achieve Tunnel control-plane ready;
- discover the connector in ChatGPT;
- complete the real ChatGPT → Tunnel → MCP probe;
- complete a real registered-project Draft PR task;
- sign and notarize a future public distribution.

No local or CI simulation can close these items.
