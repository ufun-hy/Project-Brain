# RFC-001: Local Bridge

Status: Draft  
Created: 2026-07-12  
Type: Experiment-derived RFC

## Problem

ChatGPT can read a connected GitHub repository, but the current GitHub integration cannot write repository files. ChatGPT also cannot directly access a user's local filesystem or execute commands on a local Mac.

The user needs planning performed in ChatGPT to become project assets without manually copying prompts or document contents between ChatGPT, Codex, terminals, and computers.

## What happens if we do nothing

Every handoff requires manual copying. Project decisions remain trapped in chat history, local execution becomes disconnected from planning, and switching computers requires reconstructing context.

## Verified workflow

The following workflow was verified end to end on July 12, 2026:

```text
ChatGPT
  -> Gmail task message
  -> local Project Brain Bridge
  -> registered Git repository
  -> task branch
  -> file changes
  -> commit
  -> push
  -> Draft pull request
```

The first successful verification created GitHub pull request #1 in `ufun-hy/Project-Brain`.

## Role of Gmail

Gmail is only a transport adapter. It is not the Project Brain storage layer, execution engine, or source of truth.

It is currently used because ChatGPT can send Gmail messages and the local Bridge can read them through the Gmail API. The transport may be replaced later without changing the repository workflow.

## Bridge responsibilities

The local Bridge is responsible for:

- reading trusted task messages
- validating structured JSON input
- resolving a registered local repository
- creating an isolated task branch
- applying an approved task type
- committing the result
- pushing the branch
- opening a Draft pull request
- preventing duplicate execution

## Supported task types

The current implementation supports:

- `write_files`
- `codex`
- `command` using locally defined command names

## Security boundaries

The Bridge intentionally does not permit:

- arbitrary shell commands supplied by email
- access to repositories missing from the local allowlist
- direct commits to `main` or `master`
- paths that escape the selected repository
- repeated execution of the same Gmail message

These restrictions are part of the design, not temporary omissions.

## Evidence

The verified run produced:

- a parsed Project Brain task email
- branch `brain/write_files-f9aae87e10`
- committed file `docs/bridge-v2-verification.md`
- a pushed branch
- Draft pull request #1
- successful merge into `main`

## Current decision

Keep the Bridge small and adapter-based. Do not treat Gmail as a permanent architectural dependency. Add new transport or execution capabilities only after a real workflow requires them.

## Next validation

Use the Bridge for a real project change, then verify that another computer can pull the merged result and continue work without access to the original ChatGPT conversation.
