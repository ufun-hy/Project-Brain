# Project Brain Core v3 gap analysis

Date: 2026-07-14
Baseline: `3417dec` (`origin/main`)

## Existing behavior

Bridge v2 can read trusted Gmail messages, validate three task types, run a task
in a registered repository, commit, push, and create a Draft pull request. Its
six automated tests cover the previous single-checkout branch cleanup and retry
helpers.

## Gaps addressed by Core MVP

| Area | Bridge v2 baseline | Core MVP target |
| --- | --- | --- |
| Runtime boundary | Config, JSON state, results, logs, and OAuth files live beside source | All mutable non-secret state lives under an overridable runtime root |
| Project identity | Config key and local path | Stable `project_id` persisted in SQLite |
| Task identity | Gmail `message_id` | Stable `task_id`, logical `dedupe_key`, and revision |
| Persistence | Several mutable JSON files | Versioned SQLite schema with append-only events |
| Repository isolation | Switches and cleans the main checkout | One registered task worktree per task |
| Execution state | Processed/failed JSON and uniform retry count | Explicit state machine and classified retry behavior |
| Codex result | Only inspects dirty files | Normalizes uncommitted changes, commits, and cherry-picks; rejects unsafe history |
| Review | A successful run is treated as done | Evidence is recorded and success stops at `awaiting_review` |
| Process safety | Polling daemon can overlap | `flock` singleton and at most one claimed task per apply process |
| Operations | Inspect JSON/log files manually | Human and JSON CLI status, health, task, project, and cleanup views |
| Gmail ownership | Gmail loop directly performs Git/Codex work | Gmail only parses and enqueues canonical tasks |

## Compatibility constraints

- Legacy Gmail JSON remains accepted.
- Legacy Bridge v2 config can be imported explicitly and is never deleted.
- Existing OAuth files and JSON state are not migrated or removed automatically.
- PR #10 and PR #11 are separate open Draft PRs and are not modified by this
  implementation.
- The old main-checkout cleanup behavior is intentionally retired because Core
  never runs a task in the main checkout.
