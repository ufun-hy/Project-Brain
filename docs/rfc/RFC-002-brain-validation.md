# RFC-002: Project Brain Validation

Status: Draft  
Created: 2026-07-12  
Type: Design RFC

## Problem

Project Brain can preserve project context across computers, AI sessions, and execution tools, but the context files can gradually become stale, duplicated, contradictory, or overloaded.

Without validation, a project may appear to have a Project Brain while still failing the real handoff test:

- `AGENTS.md` accumulates changing project status instead of stable work rules
- `.brain/current.md` stops reflecting the actual active task
- `.brain/decisions.md` duplicates architecture or historical documentation
- important safety boundaries disappear during edits
- a new AI session reads the files but still cannot identify the next concrete action
- secrets, customer data, screenshots, or other sensitive runtime material are accidentally committed

Project Brain therefore needs a validation mechanism that checks both document structure and context recovery quality.

## Goal

Define a small, project-independent validation model that can answer:

1. Are the required Project Brain files present and readable?
2. Does each file stay within its intended responsibility?
3. Is the current-state handoff fresh and actionable?
4. Are important decisions and safety boundaries still recoverable?
5. Can a new AI session continue the project without access to the original conversation?

## Non-goals

This RFC does not require Project Brain to:

- duplicate source code, tests, architecture documents, or product specifications
- prove that the implementation matches every statement in the context files
- replace code review, tests, CI, or security scanning
- require an LLM for every validation run
- enforce one identical document structure for every project
- automatically merge or approve pull requests

## Source-of-truth model

Project Brain validation assumes the following responsibility boundaries.

### `AGENTS.md`

Stable instructions for how humans and AI agents should work in the repository:

- required startup reading order
- architecture boundaries that must not be violated
- privacy and security constraints
- test and review expectations
- prohibited actions

It should not be the primary home for frequently changing progress, active tasks, or temporary blockers.

### `.brain/current.md`

The current project handoff:

- current stage
- active task
- recently confirmed facts
- blockers or uncertainties
- next concrete starting point
- current scope limits
- task-specific files that should be read next

It should remain short enough to scan at the start of every session.

### `.brain/decisions.md`

The small set of still-active decisions that materially affect future work:

- decision
- reason
- constraints or consequences
- conditions for re-evaluation
- references to canonical long-form documentation

It should not become a complete project history or architecture reference.

### Optional `.brain/problem.md`

A project may use `.brain/problem.md` when the core problem is not already clear and stable in `README.md` or another canonical document.

Projects are not required to duplicate an adequate README.

### `docs/`

Detailed specifications, architecture, task documents, implementation plans, historical memory, and engineering lessons.

### Code, tests, and Git history

The source of truth for actual implementation state.

Project Brain files describe where to look and why; they do not replace verification against code and tests.

## Validation levels

Validation is divided into four levels so deterministic checks can run without an AI model, while deeper recovery checks remain optional.

## Level 0: Structure

Required checks:

- `.brain/current.md` exists
- `.brain/decisions.md` exists
- files are readable UTF-8 text
- files are not empty
- referenced local paths use repository-relative paths
- Project Brain files are tracked by Git unless explicitly configured otherwise

Optional project profiles may add or remove required files, but `.brain/current.md` remains the minimum handoff document.

## Level 1: Deterministic content checks

The validator should check for objectively detectable problems.

### Current-state checks

`.brain/current.md` should contain identifiable sections or equivalent content for:

- current stage
- active task
- next starting point
- blockers, uncertainties, or an explicit statement that none are known
- last updated date

Warnings should be produced when:

- the last updated date is older than the configured freshness threshold
- the next step is vague, such as only saying “continue development”
- the file contains a long completed-task history better suited to Git or project memory
- absolute local paths appear without a clear reason

The default freshness threshold is 30 days and is advisory, not universal.

### Decision checks

`.brain/decisions.md` should use stable decision identifiers when practical, for example `DEC-001`.

Warnings should be produced when a decision lacks:

- the decision itself
- the reason
- consequences or constraints
- a re-evaluation condition when the decision is not permanent

Warnings should also be produced for likely architecture dumps, command references, large API examples, or chronological task logs.

### AGENTS boundary checks

When `AGENTS.md` exists, warn on likely current-status content such as:

- “currently working on”
- dated implementation progress
- temporary blockers
- active TODO lists
- current sprint or phase details

This is a heuristic warning. Stable architecture and safety boundaries must remain allowed even if they mention project stages.

### Privacy and secret checks

The validator must reject obvious committed secrets or sensitive runtime material in Project Brain files, including:

- private keys or access tokens
- OAuth credentials
- passwords
- raw customer conversations
- unredacted order, account, or customer identifiers
- local screenshots or binary runtime artifacts

This check complements, but does not replace, repository secret scanning.

## Level 2: Cross-document consistency

Cross-document validation should detect likely contradictions or duplication.

Examples:

- `AGENTS.md` says automatic sending is prohibited while `.brain/current.md` says it is enabled
- `.brain/current.md` names an active task that `.brain/decisions.md` explicitly forbids
- current-state content is substantially duplicated in `AGENTS.md`
- a decision is copied from a canonical architecture or memory document instead of referencing it
- two files claim different next steps or automation levels

Level 2 may combine deterministic rules with optional model-assisted analysis.

Model-assisted findings are advisory unless a project explicitly promotes a rule to blocking status.

## Level 3: Context recovery test

The strongest validation is a simulated clean-session handoff.

The evaluator may read only:

- `AGENTS.md`, when present
- `.brain/current.md`
- `.brain/decisions.md`
- `.brain/problem.md`, when present

It must answer:

1. What problem does the project solve?
2. What stage is the project currently in?
3. What is the active task?
4. What is the next concrete starting point?
5. What actions are currently prohibited or constrained?
6. Which additional files should be read for the active task?
7. Which facts cannot be confirmed from the allowed context?

### Recovery scoring

Score each category from 0 to 2:

- project purpose
- current stage
- active task
- next starting point
- constraints and safety boundaries
- uncertainty handling

Maximum score: 12.

Initial recommended passing threshold: 10, with no zero score for constraints and safety boundaries.

A recovery failure is evidence that the context files need improvement. It is not evidence that the evaluator should read every document automatically.

## Severity model

Validator findings use three severities.

### Error

Blocks validation:

- missing required file
- unreadable or invalid file
- obvious secret or sensitive customer data
- contradictory safety boundary promoted to a blocking project rule
- missing next starting point when the project requires an active handoff

### Warning

Does not block initially:

- stale current-state date
- likely responsibility overlap
- vague next action
- duplicated long-form documentation
- incomplete decision metadata
- model-assisted consistency concern

### Info

Guidance only:

- optional section missing
- possible canonical document reference
- suggested cleanup or archive action

## CLI contract

The future validator should expose a repository-local or globally installed command:

```text
brain-check
brain-check --format json
brain-check --recovery
brain-check --strict
```

Recommended exit codes:

- `0`: no validation errors
- `1`: one or more validation errors
- `2`: configuration or validator execution failure

Warnings do not change the exit code unless `--strict` is enabled.

Example human-readable output:

```text
PASS  .brain/current.md exists
PASS  .brain/decisions.md exists
WARN  .brain/current.md was last updated 41 days ago
WARN  AGENTS.md may contain active project status
PASS  no obvious secrets found
PASS  context recovery score: 11/12
```

Example JSON shape:

```json
{
  "status": "warning",
  "errors": [],
  "warnings": [
    {
      "rule": "current.freshness",
      "path": ".brain/current.md",
      "message": "Last update is older than 30 days"
    }
  ],
  "recovery": {
    "score": 11,
    "maximum": 12,
    "missing": ["test command for the active task"]
  }
}
```

## Pull-request integration

Project Brain validation should run when a pull request changes any of:

- `AGENTS.md`
- `.brain/**`
- Project Brain validation configuration

Initial merge policy:

- Level 0 and blocking Level 1 errors must pass
- warnings are visible but do not block
- Level 2 model-assisted checks are advisory
- Level 3 recovery tests run when context files change and may remain advisory during the pilot phase

Projects may later promote selected warnings or recovery thresholds to required checks.

## Bridge and Codex integration

A local Bridge or Codex task may run `brain-check` before committing or opening a pull request.

The preferred task sequence is:

```text
read Project Brain context
  -> perform the scoped task
  -> update current context when project state changed
  -> run code and project tests
  -> run brain-check
  -> commit
  -> push
  -> open Draft pull request
```

A validation failure should not trigger destructive rollback of useful work. The task should preserve the branch, report the findings, and leave the pull request in Draft state for review.

## Configuration

The first implementation should use useful defaults and avoid requiring configuration for every project.

Optional repository configuration may later define:

- required Project Brain files
- freshness threshold
- blocking and advisory rules
- canonical documentation paths
- recovery-test threshold
- sensitive path patterns
- whether a project is currently expected to have an active task

Configuration should not duplicate project content.

## Adoption plan

### Phase 1: RFC and manual checklist

- approve this responsibility model
- use it during Project Brain reviews
- collect false positives from real projects such as `kefu-ai`

### Phase 2: Deterministic CLI

Implement:

- structure checks
- required-section checks
- freshness checks
- obvious responsibility-boundary heuristics
- secret and sensitive-content checks
- text and JSON output

### Phase 3: GitHub Action

- run deterministic validation on relevant pull requests
- publish findings as a check result
- block only validation errors

### Phase 4: Optional recovery evaluator

- run the clean-session prompt when context files change
- report score and missing information
- keep results advisory until the evaluator is stable

### Phase 5: Local execution gate

- allow Bridge and Codex workflows to call the validator before Draft PR creation
- preserve failed work for inspection rather than deleting it

## Acceptance criteria

This RFC is successful when:

1. A project can run deterministic checks without an AI model.
2. Validation distinguishes errors from advisory quality warnings.
3. A new session can identify the current task and next starting point from the minimal context set.
4. Safety boundaries cannot silently disappear without producing a visible finding.
5. The validator encourages references to canonical documents instead of copying them.
6. Project Brain remains small and does not become a second documentation system.

## Current decision

Build validation incrementally.

Start with deterministic structure, freshness, responsibility, and privacy checks. Treat semantic duplication and recovery scoring as advisory during the pilot. Promote rules to blocking only after they have been tested on real projects and shown to produce low-noise results.

The validator exists to prevent context decay, not to reward larger documentation sets.
