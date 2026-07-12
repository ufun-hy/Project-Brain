# Decisions

## D-001: Project state belongs to the project

The durable context must live with the project rather than inside ChatGPT, Codex, Notion, Obsidian, or any single tool.

## D-002: GitHub is a synchronization carrier

GitHub is currently used to version and synchronize Project Brain files across computers. It is not Project Brain itself.

## D-003: Separate planning from execution

ChatGPT is used primarily for planning, clarification, and reasoning. Codex is used only when code execution or repository-level implementation is needed.

## D-004: Use a local Bridge for execution

Because the ChatGPT GitHub connection is read-only, a local Bridge receives structured tasks through Gmail and performs controlled Git operations.

## D-005: Keep the first state model minimal

The first experiment uses only `problem.md`, `current.md`, and `decisions.md`. Tasks, events, databases, knowledge graphs, and MCP integrations are deferred until real usage proves they are necessary.

## D-006: Do not execute arbitrary remote shell commands

The Bridge may write files, invoke Codex in registered repositories, or run locally allowlisted commands. It must not execute arbitrary shell text received from email.
