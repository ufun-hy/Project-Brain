# TEST EVIDENCE — Project Brain Web E2E — 2026-08-09

## Scope and immutable boundaries

This record defines the non-sensitive acceptance sequence for the PR #19 candidate:

- Candidate head: `5eca772453437968eb9af1f353959e79f2f12d0b`
- Candidate parent: `7b43c3f7363a68b2c4ebfd6e351cef623c331399`
- The candidate is evaluated as the exact head above; a later descendant is a different state.
- This delivery adds exactly one documentation artifact. It does not change application source, configuration, schemas, tests, CI, Gmail integration, or MenuBar code.
- Existing task `local-4b974b134ee13e6e9ac4a805` and existing Draft PR #19 are observation-only. No pre-existing task or PR is modified.
- No merge is part of this acceptance record.

The artifact is delivered in one new Draft PR. That delivery PR remains Draft, is not reviewed, is not marked ready, and is not merged.

## Environment identity

Record only these bounded identifiers and outcomes:

- Repository: `ufun-hy/Project-Brain`
- Candidate head and parent SHA above
- Analyze task: `pb-pr19-web-e2e-analyze-20260809-02`
- Frozen Analyze result SHA-256: `149d268e303a8528d03662fa0cabad15de5f40ad876d7d1f869d597afcbc71a8`
- Existing candidate PR: `#19`
- Implement task ID, delivery-PR number, review verdicts, commit SHAs, hashes, and pass/fail facts as they become available

Do not record prompts, raw analysis output, source contents, credentials, confirmation tokens, runtime paths, commands, environment data, email addresses, or raw logs.

## Acceptance sequence

The sequence below is the complete bounded workflow. Each action is performed only in the authorized candidate or disposable negative-test state; the observation-only boundaries above remain in force.

| Stage | Action | Evidence boundary | Required result |
| --- | --- | --- | --- |
| Analyze intake | Create an Analyze draft, explicitly confirm it, and dispatch it. | Task ID and bounded status only. | Dispatch is explicit and the task reaches completed Analyze. |
| Analyze visibility | Read the completed task through `tasks_get`. | Normalized metadata and the fixed hash only. | `schema_version=1`, `kind=analysis`, and a non-empty summary are visible. |
| Restart persistence | Restart Core, then read the same task again. | Equality of bounded result/hash values only. | `analysis_result` and `analysis_result_sha256` are identical before and after restart. |
| Implement linkage | Create an Implement draft with the original `analysis_task_id`, explicitly confirm it, and dispatch it. | Linked task IDs and fixed hash only. | The Implement uses the frozen Analyze result and does not load a newer analysis. |
| New Draft PR delivery | Commit and push only this documentation artifact, then open one new Draft PR. | Delivery commit SHA, PR number, status, and scope only. | The new PR is Draft and unmerged. It is not marked ready and receives no review or merge action. |
| Candidate review at H1 | Observe the candidate PR at its exact head `H1` and record `needs_changes`. | `H1`, PR number, verdict, and pass/fail only. | The verdict applies to the exact head being reviewed; no moving-head review is accepted. |
| Descendant correction | Observe the correction as descendant head `H2`. | `H1`, `H2`, ancestry fact, and pass/fail only. | `H2` is a descendant of `H1`; unrelated or non-descendant heads are rejected. |
| Candidate approval at H2 | Observe the candidate PR at exact head `H2` and record `approved`. | `H2`, PR number, verdict, and pass/fail only. | Approval applies to `H2` exactly. |
| Final state | Confirm the candidate PR remains Draft and unmerged. | PR number, Draft state, unmerged state, and pass/fail only. | No merge occurs, and no pre-existing PR is changed. |

## Analyze-result persistence and freeze contract

The approved Analyze snapshot is immutable implementation context. Its required identity is task `pb-pr19-web-e2e-analyze-20260809-02` and SHA-256 `149d268e303a8528d03662fa0cabad15de5f40ad876d7d1f869d597afcbc71a8`.

The acceptance evidence must establish that:

- The result is normalized as `schema_version=1`, `kind=analysis`, with a non-empty summary.
- `analysis_result_sha256` is exactly 64 lowercase hexadecimal characters.
- Recomputing the canonical JSON hash produces the stored hash.
- Restarting Core leaves both the bounded `analysis_result` and its hash unchanged.
- `project_brain_tasks_get` exposes bounded Analyze evidence and the fixed hash.
- Implement creation rejects a completed Analyze task with a missing frozen result or hash.
- Implement creation rejects a frozen result/hash mismatch.
- Dispatch rejects a linked Implement whose copied frozen result is absent or tampered.
- A later Implement prompt carries the original `analysis_task_id` and frozen hash; it never reloads a newer Analyze result.

For negative cases, use disposable SQLite state only. Never mutate the registered runtime, the existing task, or PR #19 to produce missing-result or tampered-hash evidence.

## Exact-head and ancestry evidence

The candidate identity is the exact pair `parent 7b43c3f7363a68b2c4ebfd6e351cef623c331399` → `head 5eca772453437968eb9af1f353959e79f2f12d0b`. The candidate head must resolve and its first parent must equal the recorded parent.

For the review lifecycle, record only the following bounded facts:

1. `needs_changes` is attached to the exact candidate PR head `H1`.
2. The correction head `H2` is a descendant of `H1`.
3. `approved` is attached to exact head `H2`.
4. The candidate PR is still Draft and has no merge result.

A review attached to any other head, or a correction that is not a descendant of `H1`, is not acceptance evidence.

## Privacy exclusions

This document intentionally excludes credentials, confirmation tokens, local filesystem paths, runtime secrets, private runtime data, customer data, user data, prompts, raw model output, source contents, commands, environment details, email addresses, and raw logs. Evidence is limited to bounded statuses, task IDs, PR numbers, commit SHAs, SHA-256 values, review verdicts, ancestry facts, and pass/fail outcomes.

## Risks, pending external dependencies, and rollback scope

Pending external dependencies are the authorized disposable candidate environment, Core restart behavior, GitHub exact-head review state, and the ability to keep the new delivery PR Draft and unmerged. These dependencies must not be satisfied by changing PR #19 or the registered task.

The primary risks are stale or substituted Analyze results, hash tampering, review drift between `H1` and `H2`, and accidental merge or readiness actions. The frozen hash, copied-result validation, exact-head checks, descendant check, and final Draft/unmerged check bound those risks.

Rollback is limited to this single documentation artifact or its one documentation-only delivery commit. No source, schema, configuration, runtime database, existing task, branch, or pre-existing PR rollback is authorized.
