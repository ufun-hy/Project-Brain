# Product Shell RC1 Build 5 hotfix verification

Base: `main@7a8275289ac949f418d60a7d20cca14a8ae728f9`

Version: `0.7.0 (5)`

Build 4 is immutable release-candidate history. Build 5 supersedes Build 4 for
onboarding and installation acceptance; Build 4 must not be deleted, rebuilt,
or overwritten.

## Repository gates

- Existing repositories are resolved by canonical real path, normalized Git
  origin, and registered project identity before an add plan is shown.
- An unchanged existing registration produces `use_existing`; an actual
  execution-profile change produces `update` while retaining the registered ID
  and display name.
- ID, display-name, and repository-path conflicts are structured plan-time
  errors. Apply repeats resolution under the runtime lock and the SQLite
  transaction retains final name, path, revision, hash, and action checks.
- The onboarding sheet renders errors inline and offers bounded recovery:
  select the existing project, choose another directory, or edit the name.
- A copy launched from a mounted DMG or any location other than
  `/Applications/Project Brain.app` is explicitly not installed. It may be used
  for exploration, but local readiness and formal acceptance remain blocked
  until the installed copy is launched.
- Upgrades preserve the existing SQLite database, project registrations,
  configuration revisions, task history, services, and Keychain data.

## Artifact boundary

CI publishes the distinct artifact `Project-Brain-RC1-Build5-arm64`, containing
`Project-Brain-RC1-Build5-arm64.dmg`,
`Project-Brain-RC1-Build5-arm64.zip`, `build-manifest.json`, and `SHA256SUMS`.
The manifest binds the exact Git head, app `0.7.0 (5)`, Core helper SHA-256,
artifact SHA-256 values, and the GitHub Actions run URL.

The build remains an unsigned, unnotarized internal RC. Secure MCP Tunnel and
External ChatGPT acceptance remain Pending and cannot be closed by local or CI
transport tests.
