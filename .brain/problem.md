# Problem

Project Brain exists to connect ChatGPT's planning and review with reliable local Codex execution.

## Real problem

The useful workflow is simple:

1. Discuss and decide the work in ChatGPT.
2. When the user says to hand it to Codex, send the final implementation task to the correct local repository.
3. Run Codex in an isolated worktree without disturbing the user's main checkout.
4. Run the task or project checks.
5. Return the code changes, test results, and blockers to ChatGPT for review.

The problem is not task-management UI, PR automation, or a second review system. The problem is making the ChatGPT -> local Codex handoff reliable without making the user operate internal orchestration details.

## Current goal

Build the smallest useful local bridge for personal use:

`ChatGPT -> MCP -> Project Brain -> isolated worktree -> Codex CLI -> checks -> ChatGPT review`

## Constraints

- ChatGPT owns discussion, analysis, product decisions, task framing, and final review.
- Codex owns bounded local implementation and required checks.
- Project Brain is transport and execution infrastructure, not a second planning or review product.
- The registered main checkout must never be used as the Codex working directory or reset/cleaned by Project Brain.
- External input must not become arbitrary shell authority.
- Failure stops and returns evidence; Project Brain does not automatically retry or redesign the task.
- No automatic commit, push, pull request, merge, or publication lifecycle is required for normal tasks.
- The product is currently personal/internal; App packaging and public distribution are not priorities.
- Keep the implementation small. Add abstractions only when real usage proves they are necessary.
