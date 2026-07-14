"""Codex process adapter; all calls are scoped to a task worktree."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

from .errors import ExternalCommandError, InvalidTaskError, TransientTaskError
from .git_history import GitHistoryNormalizer, GitSnapshot, NormalizedHistory
from .store import TaskStore
from .security import redact_text


class CodexAdapter:
    def __init__(self, store: TaskStore, normalizer: GitHistoryNormalizer | None = None) -> None:
        self.store = store
        self.normalizer = normalizer or GitHistoryNormalizer()

    def execute(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: str | Path,
        snapshot: GitSnapshot,
    ) -> NormalizedHistory:
        prompt = task["payload"].get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidTaskError("codex task requires a non-empty prompt")
        command = project.get("codex_command")
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item for item in command
        ):
            raise InvalidTaskError("codex_command must be a non-empty array of strings")
        session_id = str(uuid.uuid4())
        self.store.record_agent_session(
            session_id=session_id,
            task_id=task["task_id"],
            adapter="codex",
            command=command,
        )
        timeout = int(task["payload"].get("timeout_seconds", 1800))
        try:
            completed = subprocess.run(
                command,
                cwd=str(Path(worktree).resolve()),
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            self.store.finish_agent_session(
                session_id,
                status="failed",
                exit_code=None,
                output_summary=f"Command not found: {command[0]}",
            )
            raise ExternalCommandError(f"Command not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            self.store.finish_agent_session(
                session_id,
                status="timed_out",
                exit_code=None,
                output_summary=f"Timed out after {timeout}s",
            )
            raise TransientTaskError(f"Codex timed out after {timeout}s") from exc
        summary = redact_text((completed.stdout + "\n" + completed.stderr).strip())[-4000:]
        self.store.finish_agent_session(
            session_id,
            status="completed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            output_summary=summary,
        )
        if completed.returncode != 0:
            raise ExternalCommandError(
                f"Codex failed with exit code {completed.returncode}: {summary}",
                returncode=completed.returncode,
            )
        message = task["payload"].get("commit_message") or f"feat: complete {task['task_id']}"
        if not isinstance(message, str) or not message.strip():
            raise InvalidTaskError("commit_message must be a non-empty string")
        return self.normalizer.normalize(worktree, snapshot, message=message)
