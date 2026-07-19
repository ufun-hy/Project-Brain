# Product Shell Build 9 plan/confirm verification

Build 9 updates the existing Draft PR #18 from exact RFC-008 base
`7259acfa1c38e30f3f8c2126eb7c7c3f8c271e3f`. It does not reuse or overwrite
the immutable Build 8 artifact.

The reviewed two-step failure evidence, F1–F3 boundary, four-step Build 9 flow,
feedback budgets, and token-only confirmation design are captured in the
[Build 8 UX Audit / Build 9 Fix board](https://www.figma.com/board/LvXMFQJJYsUdTQD8vlMCIE/Project-Brain-Build-8-UX-Audit---Build-9-Fix?node-id=0-1&p=f&t=0bKcBHDYNDSLBh6B-0).

## Closure

- F1: schema v10 stores one canonical request, request hash, reviewed plan hash,
  project revision/hash, remote Base, delivery, timestamps, contract version,
  and only the transient token's SHA-256. Confirm accepts exactly `plan_token`
  and `expected_plan_hash`; task creation and consumption are atomic.
- F2: the App uses explicit phases, captures immutable values before asynchronous
  work, performs one plan and one create helper call, opens Task Center from the
  minimal create response, and refreshes only the selected task in the background.
- F3: Core emits structured error/recovery metadata and a correlation ID. The
  ordinary task sheet maps codes to English and Simplified Chinese resources,
  returns goal errors to editing, and never displays raw Core English text.
- F4: the default review shows user effects and risks. Paths, Base/profile
  hashes, executable, worktree, expiry, and schema/contract are collapsed.
  Only a short token fingerprint can be shown.

## Final artifact verification

macOS CI builds `Project-Brain-Local-Tasks-Build9-arm64` as an unsigned,
unnotarized seven-day DMG/App ZIP artifact with a schema-v4 manifest. The final
DMG test installs the App into `/Applications`, migrates an intact schema-v9
runtime, and launches the final App executable in an isolated CI-only probe.
That executable uses its bundled CLI contract and embedded helper to plan and
confirm the exact reported Chinese goal. The test deliberately mutates its
client request after planning, verifies that only token/hash confirmation is
used, completes the no-change Analyze task, restarts the final App, and reads
the same goal, result, and evidence. The repository HEAD/status and fixture
runtime data remain unchanged apart from the intended schema migration/task.

The artifact includes redacted timing evidence for cold/warm planning,
open-sheet model setup, click feedback, create transaction, and background task
refresh. It contains no goal text, token, credential, or complete user path.

Secure MCP Tunnel and real ChatGPT connector acceptance remain **Pending**.
Local App/Core verification cannot satisfy or replace external acceptance.
