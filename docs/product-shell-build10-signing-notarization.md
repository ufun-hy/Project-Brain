# Product Shell Build 10 signing and notarization

## Status and evidence boundary

Project Brain 0.8.0 (10) adds the repository-side F5 release gate. Build 9 is
immutable internal-build history and must not be deleted, rebuilt, overwritten,
or relabeled. Pull-request CI creates only
`Project-Brain-Build10-Preflight-Unsigned-arm64`; that package is
non-distributable and is not uploaded.

The final `Project-Brain-Build10-arm64` artifact does not exist until the
protected release workflow completes with real Apple credentials. Repository
tests, a locally fabricated signature, ad-hoc signing, or removing quarantine
cannot substitute for Developer ID signing, Apple notarization, or the final
fresh-Mac GUI acceptance.

## Apple prerequisites

The release operator needs:

- an active Apple Developer Program membership;
- a `Developer ID Application` certificate and private key exported as PKCS#12;
- the exact certificate identity and Apple Team ID;
- an App Store Connect API key authorized for notarization, including its key
  ID, issuer ID, and `.p8` private key.

Apple's release requirements are described in
[Developer ID](https://developer.apple.com/support/developer-id/) and
[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

Configure these GitHub environment secrets in the protected
`macos-release` environment:

| Secret | Content |
| --- | --- |
| `DEVELOPER_ID_APPLICATION_P12_BASE64` | base64-encoded PKCS#12 bytes |
| `DEVELOPER_ID_APPLICATION_P12_PASSWORD` | PKCS#12 export password |
| `DEVELOPER_ID_APPLICATION_IDENTITY` | full `Developer ID Application: …` identity |
| `APPLE_TEAM_ID` | certificate Team ID |
| `APPLE_NOTARY_KEY_P8_BASE64` | base64-encoded App Store Connect `.p8` bytes |
| `APPLE_NOTARY_KEY_ID` | App Store Connect key ID |
| `APPLE_NOTARY_ISSUER_ID` | App Store Connect issuer ID |

The workflow imports credentials into an ephemeral keychain, never writes them
to the artifact or manifest, and removes the temporary keychain and key files
in an `always()` cleanup step.

## Exact-SHA release

Run the GitHub Actions workflow **macOS Developer ID release** manually and pass
the exact 40-character PR head SHA as `release_sha`. The workflow checks that
the checked-out `HEAD` is exactly that value before continuing. It performs:

1. frozen Core helper build and CLI contract validation;
2. unsigned functional preflight in a temporary, non-published directory;
3. helper signature with `Developer ID Application`, Hardened Runtime, and a
   secure timestamp;
4. signatures for any other nested Mach-O executables and
   framework/XPC/extension bundles, followed by the outer App signature with
   the same release requirements;
5. strict nested signature, Team ID, runtime, timestamp, and
   `get-task-allow` checks;
6. App submission through `xcrun notarytool`, acceptance, stapling, and ticket
   validation;
7. final App ZIP creation from the stapled App;
8. DMG creation with the App, `/Applications` link, and visible install guide;
9. DMG Developer ID signature, notarization acceptance, stapling, and
   Gatekeeper assessment;
10. schema-v5 manifest and SHA-256 bindings, final embedded-helper task flow,
    preserved schema upgrade, and single-process/window verification.

Signing uses explicit inside-out ordering. `--deep` is used only for signature
verification, never to create a signature. The script refuses to overwrite an
existing Build 10 output.

## Automated verification

The release workflow runs the equivalent of:

```bash
codesign --verify --deep --strict --verbose=2 "Project Brain.app"
spctl --assess --type execute --verbose=4 "Project Brain.app"
xcrun stapler validate "Project Brain.app"
xcrun stapler validate "Project-Brain-Build10-arm64.dmg"
spctl --assess --type open \
  --context context:primary-signature \
  --verbose=4 \
  "Project-Brain-Build10-arm64.dmg"
```

It also places a quarantine attribute on a temporary copy of the final DMG and
repeats Gatekeeper assessment. It never clears quarantine and never disables
Gatekeeper globally. This is useful automated evidence but is not a fresh Mac.

The schema-v5 manifest records:

- exact Git head and GitHub Actions run;
- App version/build/executable SHA-256;
- Core helper version/SHA-256;
- CLI contract schema/version/Core version/document SHA-256;
- Developer ID identity, Team ID, Hardened Runtime, secure timestamp, and
  absence of `get-task-allow`;
- accepted App and DMG notarization submission IDs;
- stapled App and DMG ticket state;
- final DMG, App ZIP, sanitized receipt, and manifest hashes;
- `fresh_mac_quarantine_acceptance: pending_manual`;
- `external_acceptance: pending_user_credentials_and_actions`.

The manifest intentionally retains `distribution_eligible: false` until the
manual gate below is recorded by a separately reviewed change.

## Manual fresh-Mac acceptance

Use a Mac that has never installed Project Brain and has no saved Project Brain
Gatekeeper exception:

1. download the exact Build 10 DMG through a browser so quarantine is present;
2. compare its SHA-256 with the signed workflow output;
3. mount the DMG;
4. drag `Project Brain.app` onto the visible Applications target;
5. eject the DMG;
6. launch `/Applications/Project Brain.app` by double-clicking it;
7. verify there is no “Apple could not verify” dialog and no need for a
   Privacy & Security override;
8. complete preserved-data onboarding and a real local task without clearing
   `~/.project-brain/`.

Until all steps pass and the human evidence is reviewed, F5 ordinary-user
installation acceptance remains Pending. Secure MCP Tunnel and External
ChatGPT acceptance are separate Pending gates and are never inferred from this
flow.
