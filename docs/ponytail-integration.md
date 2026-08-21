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

The official plugin normally supports SessionStart auto-activation. On the current Project Brain execution host, manual verification with Codex 0.149.0 showed that `PONYTAIL_DEFAULT_MODE=lite` reached the child process but did not by itself activate Ponytail in a fresh session. Explicit `@ponytail lite` did activate it through `UserPromptSubmit`. Project Brain therefore uses explicit prompt activation as the deterministic path and keeps the environment variable as a compatible default/fallback.

Without the plugin, the `@ponytail <mode>` prefix remains ordinary prompt text and the environment variable has no Ponytail behavior to activate. The execution host must therefore install and trust the official plugin before Ponytail policy is relied on.

## Mode resolution

Project Brain resolves the mode in this order:

1. task payload `ponytail_mode`, when present;
2. host environment `PROJECT_BRAIN_PONYTAIL_MODE`;
3. Project Brain default `lite`.

Allowed values are:

- `off` — explicitly disable Ponytail for the Codex task;
- `lite` — default; implement the requested work and prefer the simpler existing path;
- `full` — enforce the reuse/native/minimal-diff ladder more strongly for normal implementation work;
- `ultra` — aggressive YAGNI/deletion mode; use only for explicit cleanup or complexity-audit work.

Invalid values fail closed before Codex execution.

For every Codex task Project Brain applies the resolved mode in two places:

1. child environment: `PONYTAIL_DEFAULT_MODE=<mode>`;
2. first prompt line: `@ponytail <mode>`.

The explicit prompt command is the activation path. The environment variable remains useful for plugin compatibility and any future SessionStart behavior, but Project Brain does not rely on it alone.

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

The current adapter understands that payload field. Transport schemas should expose it only as an allowlisted enum; they must not allow callers to supply arbitrary environment variables, shell commands, or arbitrary prompt prefixes.

## Recommended Project Brain usage

Use `lite` as the normal default across registered projects. Use `full` for bounded implementation tasks where the requirement is already decided. Use `ultra` only for an explicit simplification/audit task, and keep the resulting deletion suggestions subject to normal ChatGPT/Codex correctness review. Use `off` when a task explicitly needs work that would be distorted by minimal-diff pressure.

Do not add an automatic mode classifier yet. ChatGPT or another trusted task producer may choose a non-default mode explicitly when the task warrants it; otherwise `lite` is enough.

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

This integration is intentionally narrow so it can be carried into the Simplified Core without reviving the legacy task/review/publication lifecycle.

When Simplified Core spawns Codex for a task it only needs to preserve this small contract:

1. resolve `ponytail_mode` from task override -> host default -> `lite`;
2. validate the value against `off|lite|full|ultra`;
3. set `PONYTAIL_DEFAULT_MODE` on the Codex child environment;
4. prefix the actual Codex task with `@ponytail <mode>` followed by a blank line;
5. keep normal repository instructions, checks, and ChatGPT review authoritative.

No Ponytail lifecycle state, retry state, acceptance gate, MCP server, or automatic review loop is required.
