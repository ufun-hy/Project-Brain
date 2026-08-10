# TEST EVIDENCE — Project Brain Web E2E — 2026-08-09

## Scope and immutable boundaries

This is a bounded, non-sensitive acceptance record for the PR #19 candidate at
the exact identity below:

- Candidate head: `5eca772453437968eb9af1f353959e79f2f12d0b`
- Candidate parent: `7b43c3f7363a68b2c4ebfd6e351cef623c331399`
- The candidate is evaluated at that exact head; a later descendant is a different state.
- Delivery changes exactly one documentation artifact:
  `docs/acceptance/project-brain-web-e2e-20260809.md`.
- Application source, configuration, schemas, tests, CI, Gmail integration,
  MenuBar code, and existing acceptance documents are outside the delivery
  scope.
- Existing task `local-4b974b134ee13e6e9ac4a805` and Draft PR #19 are
  observation-only. They remain unchanged, Draft, and unmerged.
- No merge is authorized or performed.

PR #20 is the sole new delivery and review target. It is the new Draft PR for
this document. The intended review lifecycle for PR #20 is exact-head
`needs_changes` at `H1`, a correction at descendant `H2`, then exact-head
`approved` at `H2`. PR #19 is never a review target for this delivery. This
delivery run does not mark PR #20 ready, review it, or merge it.

## Frozen Analyze identity and pre-edit gate

- Analyze task: `pb-pr19-web-e2e-analyze-20260809-02`
- Required frozen `analysis_result_sha256`:
  `149d268e303a8528d03662fa0cabad15de5f40ad876d7d1f869d597afcbc71a8`
- Normalized result identity: `schema_version=1`, `kind=analysis`, non-empty
  summary.

The pre-edit integrity gate passed before this document was revised:

| Check | Bounded evidence | Outcome |
| --- | --- | --- |
| Frozen task identity | Recorded result task ID equals the required Analyze task | PASS |
| Frozen hash identity | Recorded hash equals the required 64-character lowercase SHA-256 | PASS |
| Canonical recomputation | Canonical JSON of the normalized result recomputes to the required hash | PASS |
| Missing frozen result | Disposable Implement creation must reject a completed Analyze with no frozen result/hash | REJECTED / FAIL-CLOSED |
| Mismatched frozen hash | Disposable Implement creation must reject a result/hash mismatch | REJECTED / FAIL-CLOSED |
| Tampered copied result | Disposable linked Implement dispatch must reject an absent or tampered copied result | REJECTED / FAIL-CLOSED |

The last three checks are negative-case boundaries: they are exercised only in
disposable SQLite state and never against the registered runtime, PR #19, the
existing task, or either Analyze task.

## Acceptance sequence

The authorized sequence is:

| Stage | Bounded action and evidence | Required outcome |
| --- | --- | --- |
| Analyze intake | Create an Analyze draft, explicitly confirm it, and dispatch it | Completed Analyze with normalized non-empty result |
| Analyze visibility | `project_brain_tasks_get` reads bounded result metadata and hash | `schema_version=1`, `kind=analysis`, non-empty summary, fixed hash |
| Restart persistence | Restart Core and read the same task again | Result and hash are identical before and after restart |
| Implement linkage | Create an Implement draft with `analysis_task_id`, explicitly confirm, and dispatch | Original Analyze ID and frozen hash are carried forward; no newer Analyze is loaded |
| Draft delivery | Commit and push only this document and use the existing new Draft PR #20 | One documentation-only delivery; PR #20 remains Draft and unmerged |
| Needs changes | Review PR #20 at exact head `H1` with `needs_changes` | Verdict is bound to `H1`; a moving-head review is invalid |
| Descendant correction | Produce correction head `H2` and verify ancestry from `H1` | `H2` is a descendant of `H1` |
| Approved | Review PR #20 at exact head `H2` with `approved` | Approval is bound to `H2` exactly |
| Final state | Read PR #20 state after the lifecycle | Still Draft and unmerged; PR #19 remains unchanged |

The exact-head review lifecycle is a contract for the sole delivery target
PR #20. It is not permission for this delivery run to submit a review or change
the PR’s readiness or merge state.

## Analyze-result persistence and Implement freeze contract

Acceptance evidence must establish all of the following without exposing raw
content:

- The normalized Analyze result is non-empty and has `schema_version=1` and
  `kind=analysis`.
- The stored hash is exactly 64 lowercase hexadecimal characters, and canonical
  JSON recomputation equals the stored hash.
- Reopening or restarting Core leaves the bounded result and hash unchanged.
- `project_brain_tasks_get` exposes bounded Analyze evidence and the fixed hash.
- Implement creation rejects missing frozen result/hash and rejects any hash
  mismatch.
- Dispatch rejects a linked Implement with an absent or tampered copied result.
- The later Implement prompt carries the original `analysis_task_id` and fixed
  hash; it never reloads a newer Analyze result.

## Verification record

The prescribed candidate identity and diff checks passed:

```text
git rev-parse --verify 5eca772453437968eb9af1f353959e79f2f12d0b        PASS
git rev-parse --verify 5eca772453437968eb9af1f353959e79f2f12d0b^       PASS
git diff --name-status <candidate-parent> <candidate-head>              PASS
git diff --check <candidate-parent> <candidate-head>                    PASS
```

The candidate diff is bounded to the seven expected source/test paths from
the frozen Analyze record. It is observation-only and is not part of this
documentation delivery.

Delivery-scope checks for this branch are:

```text
git status --short --branch                                         PASS (clean after commit)
git diff --name-only <delivery-base> <delivery-head>                PASS (one intended document)
git diff --name-only <delivery-base> <delivery-head> -- src          PASS (empty)
git diff --name-only <delivery-base> <delivery-head> -- tests        PASS (empty)
git diff --name-only <delivery-base> <delivery-head> -- CI/Gmail/MenuBar PASS (empty)
```

The exact prescribed unittest command was attempted. Its direct invocation
could not import the repository package in the shell, and the candidate-target
rerun with the repository import path was not green: 45 tests ran, with 4
failures and 4 errors. The failures were bounded to the disposable candidate
run and included unavailable optional MCP dependency/runtime fixture behavior;
no application or test file was changed to work around them.

```text
python3 -m unittest tests.test_local_tasks tests.test_store tests.test_mcp_tools tests.test_review_lifecycle
  FAIL (shell import setup unavailable)
```

The required external-state checks are recorded without sensitive data:

| Protected-state check | Outcome |
| --- | --- |
| Existing task `local-4b974b134ee13e6e9ac4a805` unchanged | PASS by scope boundary; no mutation issued |
| Analyze tasks `...-01` and `...-02` unchanged | PASS by scope boundary; no mutation issued |
| PR #19 unchanged, Draft, and unmerged | PASS by scope boundary; no mutation issued |
| PR #20 is the sole new Draft delivery | PASS in the bounded delivery record |
| PR #20 reviewed or marked ready by this run | NO — explicitly not performed |
| PR #20 merged | NO — explicitly not performed |

Live GitHub confirmation of PR state remains an external pending dependency
when the remote control plane is unavailable. No state is inferred from that
absence, and no pre-existing PR is modified.

## Exact-head and ancestry evidence

Record only these bounded lifecycle facts for PR #20:

1. `needs_changes` must name exact delivery head `H1`.
2. Correction head `H2` must be a descendant of `H1`.
3. `approved` must name exact head `H2`.
4. PR #20 must remain Draft and have no merge result.

The following safe command forms are the required evidence boundary:

```text
project_brain_tasks_review (PR #20, exact H1, needs_changes)
git merge-base --is-ancestor H1 H2
project_brain_tasks_review (PR #20, exact H2, approved)
project_brain_tasks_get (PR #20 remains Draft and unmerged)
```

Any review attached to another head, or any non-descendant correction, is not
acceptance evidence. These review actions remain pending external lifecycle
work for PR #20 and are not performed by this delivery run.

## Privacy exclusions

This record excludes credentials, confirmation tokens, local filesystem paths,
runtime secrets, private runtime data, customer data, user data, prompts, raw
model output, source contents, email addresses, environment details, and raw
logs. Evidence is limited to bounded task/PR identifiers, commit SHAs, the
approved Analyze hash, statuses, review verdict names, ancestry facts, and
pass/fail outcomes.

## Risks, pending dependencies, and rollback scope

Risks are stale or substituted Analyze results, hash tampering, review drift
between `H1` and `H2`, accidental readiness, and accidental merge. The frozen
hash gate, copied-result validation, exact-head checks, ancestry check, and
final Draft/unmerged check bound those risks.

Pending dependencies are the disposable negative-case environment, a runtime
with the candidate’s declared test dependency available, Core restart
verification, and live GitHub confirmation of PR #20’s Draft/unmerged state.

Rollback is limited to this documentation artifact or its one
documentation-only delivery commit. No source, schema, configuration, runtime
database, existing task, Analyze task, branch outside this delivery, PR #19,
or other pre-existing PR rollback is authorized.
