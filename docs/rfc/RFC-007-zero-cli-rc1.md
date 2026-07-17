# RFC-007: Zero-CLI Product Shell RC1

Status: Repository implementation complete; external acceptance pending
Target: Project Brain 0.7.0 build 4
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

The installer first performs zero-execution static inspection of a regular,
non-symlink executable: bounded size, arm64 Mach-O architecture, SHA-256,
quarantine status, and code-signing validity without claiming an OpenAI identity.
Cancel executes no subprocess and installs nothing. After a separate explicit
authorization it executes only `<candidate> --version`, with a
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
back on failure. Post-activation validation includes a fixed, bounded,
non-destructive `runtimes list --json` probe under an isolated temporary HOME;
the expected aliases/admin-profile/state-root contract must decode, and its
state root must remain inside that HOME. A failure removes a fresh install or
restores the previous SHA. Removal validates the managed file and fails closed unless
the controlled runtime stop response proves `stopped` with no running process.
The installer does not remove quarantine attributes or invoke Gatekeeper
bypasses.

## MCP transport evidence and external acceptance authority

Schema v8 retains a stable per-installation UUID plus acceptance runs and
append-only events. A challenge contains 256 bits of system randomness, expires
after ten minutes, is single-use, and is returned to the app once. SQLite stores
only its SHA-256. Each run binds Core and app versions, the installation
identity, the current Tunnel ID fingerprint, acceptance contract, creation time,
and expiry.

The states are `not_started`, `challenge_ready`, `waiting_for_chatgpt`,
`mcp_transport_probe_passed`, `failed`, `expired`, and `superseded`. A new run supersedes unfinished
runs. Expiry and ingress completion use immediate SQLite transactions;
conditional mutation permits exactly one concurrent winner. Schema-v7 `passed`
rows migrate to unattributed transport evidence, never external verification.

Only the registered MCP tool `project_brain_acceptance_probe` reaches the
private completion operation. Its strict input schema contains one string field,
`challenge`, and rejects extra properties. It cannot accept command, argv,
environment, SQL, paths, or URLs; it does not execute processes, modify Git,
create tasks, or access arbitrary files. The response contains probe status,
`external_chatgpt_verified=false`, source attribution unavailable, Project Brain
version, verification time, and run ID. The loopback endpoint can be called
directly, so ordinary headers/IP/User-Agent cannot authenticate ChatGPT or the
Tunnel. Core exposes no
`acceptance pass` CLI command, and the Swift typed-command enum exposes no pass
case. UserDefaults is explicitly non-authoritative; app restart restores status
only from Core schema-v8 state.

Transport tests exercise the real Streamable HTTP initialize/list/call path,
including spoofed source headers. They record only unattributed transport
evidence. External ChatGPT acceptance remains Pending until a trusted OpenAI
control-plane attestation contract exists.

## Controlled real-project acceptance task

The fixed task is retained as a future capability, but planning fails closed
while trusted ChatGPT attestation is unavailable. Neither historical nor current
unattributed transport evidence unlocks it. Any future plan must bind an
applicable attestation plus the exact project configuration revision/hash and
continue to use the isolated worktree, immutable verification set, publication,
and Draft PR pipeline.

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
