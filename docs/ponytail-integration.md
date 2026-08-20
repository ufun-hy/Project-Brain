# Ponytail integration

## Purpose

Ponytail is an optional Codex engineering policy for Project Brain tasks. It is not a Project Brain state-machine feature, not a review authority, and not part of any managed project's production runtime.

The goal is to bias Codex toward the smallest correct implementation after it has understood the task: reuse existing code first, prefer standard-library and native-platform features, avoid speculative abstractions and dependencies, and keep diffs small without removing required validation, security, accessibility, error handling, tests, or explicit product requirements.

Project Brain remains a thin execution bridge:

`ChatGPT -> MCP -> Project Brain -> isolated worktree -> Codex CLI -> checks -> ChatGPT review`

## One-time Codex setup on the execution host

Install the official Ponytail Codex plugin on the machine that runs Project Brain's Codex CLI:

```bash
codex plugin marketplace add DietrichGebert/ponytail
codex plugin add ponytail@ponytail
```

Open Codex, run `/hooks`, review and trust Ponytail's lifecycle hooks, then start a new Codex session. Project Brain does not install or vendor Ponytail automatically.

Without the plugin, Project Brain's mode environment variable is harmless but has no Ponytail behavior to activate.

## Mode resolution

Project Brain resolves the mode in this order:

1. task payload `ponytail_mode`, when present;
2. host environment `PROJECT_BRAIN_PONYTAIL_MODE`;
3. Project Brain default `lite`.

Allowed values are:

- `off` — no Ponytail policy;
- `lite` — default; implement the requested work and prefer the simpler existing path;
- `full` — enforce the reuse/native/minimal-diff ladder more strongly for normal implementation work;
- `ultra` — aggressive YAGNI/deletion mode; use only for explicit cleanup or complexity-audit work.

Project Brain passes the resolved value to the Codex child process using Ponytail's official `PONYTAIL_DEFAULT_MODE` environment variable. Invalid values fail closed before Codex execution.

To change the default for the Project Brain host:

```bash
export PROJECT_BRAIN_PONYTAIL_MODE=lite
```

A task producer that supports optional execution policy may add:

```json
{
  "payload": {
    "prompt": "Implement the approved change.",
    "ponytail_mode": "full"
  }
}
```

The current adapter already understands that payload field. Transport schemas should expose it only as an allowlisted enum; they must not allow callers to supply arbitrary environment variables or shell commands.

## Recommended Project Brain usage

Use `lite` as the normal default across registered projects. Use `full` for bounded implementation tasks where the requirement is already decided. Use `ultra` only for an explicit simplification/audit task, and keep the resulting deletion suggestions subject to normal ChatGPT/Codex correctness review. Use `off` when a task explicitly needs an architecture exploration that would be distorted by minimal-diff pressure.

Do not make Ponytail a required acceptance gate. Ponytail review is about unnecessary complexity; it does not replace correctness, security, performance, product-contract, migration, permission, or test review.

## Precedence

The managed repository's own instructions and the user's explicit task always win. In particular, Ponytail must never simplify away:

- trust-boundary validation;
- security or permission checks;
- data-loss prevention and required error handling;
- accessibility requirements;
- required migrations, auditability, idempotency, or tenant isolation;
- repository-required documentation and tests;
- explicit acceptance criteria.

Ponytail changes how Codex chooses an implementation, not what the product contract requires.

## Simplified Core port

This integration is intentionally narrow so it can be carried into the Simplified Core without reviving the legacy task/review/publication lifecycle. The only runtime requirement is: when spawning Codex for a task, inherit the current environment and set `PONYTAIL_DEFAULT_MODE` to the resolved Project Brain mode.
