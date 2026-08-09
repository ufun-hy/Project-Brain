# Product Shell Build 10 Personal Build

## Scope

Project Brain 0.8.0 (10) is currently a personal internal tool. The artifact is
`Project-Brain-Build10-Personal-Unsigned-arm64`: an unsigned, unnotarized DMG
and App ZIP for the owner's own Mac. It is never eligible for public
distribution.

The schema-v5 manifest records:

- `artifact_classification: unsigned_personal_build`;
- `usage_scope: personal_internal_only`;
- `distribution_eligible: false`;
- exact Git head, CI run, App executable, Core helper, CLI contract, DMG, and
  App ZIP hashes;
- Developer ID signing, Apple notarization/stapling, and Fresh-Mac public
  distribution acceptance as `deferred_personal_use`;
- `personal_gatekeeper_authorization: required_manual_per_artifact`;
- External ChatGPT acceptance as `pending_user_credentials_and_actions`.

The manifest and `SHA256SUMS` contain no credential, Tunnel ID, plaintext
challenge, user runtime path, project data, or task payload.

## Generate and download

Pull-request CI uploads an artifact from the exact tested PR head. After the
workflow file exists on `main`, the owner may also run **macOS Personal Build**
manually with an exact 40-character `build_sha`. That workflow:

1. checks out and verifies the requested SHA;
2. uses no Apple signing key, notary credential, or repository secret;
3. runs Python, launchd, SwiftPM, Xcode, final embedded-helper, preserved-schema,
   single-instance, and Gmail-isolation verification;
4. uploads the DMG, App ZIP, `build-manifest.json`, and `SHA256SUMS` for 30 days.

GitHub only allows a manual `workflow_dispatch` after its workflow exists on the
default branch. Before PR #18 is merged, use the Personal Build artifact from
the PR's ordinary **Core tests** run.

## Install safely

1. Compare the DMG SHA-256 with `SHA256SUMS` and `build-manifest.json`.
2. Open the DMG and drag `Project Brain.app` to the adjacent Applications link.
3. Eject the DMG and start `/Applications/Project Brain.app` from Finder.
4. If Gatekeeper blocks the known artifact, click **Done**, then use **System
   Settings → Privacy & Security → Security → Open Anyway**. Authenticate and
   confirm **Open**.

macOS may ask again after a new build changes the App bytes. Only authorize an
artifact whose source and checksum were verified. Never use
`spctl --master-disable` and never recursively remove quarantine attributes.
The manual exception does not count as Developer ID signing, Apple notarization,
or public-distribution acceptance.

## Deferred and Pending gates

The following are **Deferred — personal use** and do not block PR #18:

- Developer ID Application signing;
- Apple notarization and App/DMG stapling;
- Fresh-Mac public-distribution acceptance without a Gatekeeper override.

The existing `macOS Developer ID release` workflow remains fail-closed for a
future public release. When public distribution resumes, those gates return to
Pending and require real Apple credentials and fresh-Mac evidence.

External ChatGPT acceptance is different: it remains **Pending** and requires
the user's real credentials and GUI actions. No local task, transport probe,
artifact test, or manual Gatekeeper exception can mark it passed.
