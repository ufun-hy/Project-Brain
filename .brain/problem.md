# Problem

Project Brain exists to preserve the working context of a software project across computers, AI tools, and sessions.

## Real problems

- Project knowledge is often scattered across chat history, people, machines, and temporary AI sessions.
- Git preserves code and changes, but not always the reasons, constraints, and current intent behind them.
- ChatGPT is useful for planning and reasoning, while Codex is useful for execution, but the project state should not belong to either tool.
- Work should be resumable from another computer without repeating the full project history.

## Current goal

Prove that a minimal set of project-owned files can restore enough context for a new human or AI session to continue meaningful work.

## Constraints

- The project must remain AI-agnostic.
- Storage and transport are implementation details, not the product itself.
- The first version must stay small and be discovered through real usage.
- Every new abstraction must solve a real observed problem.
