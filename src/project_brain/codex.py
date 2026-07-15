"""Codex process adapter; all calls are scoped to a task worktree."""

from __future__ import annotations

import subprocess
import os
import threading
import uuid
from pathlib import Path
import json
from typing import Any

from .errors import ExternalCommandError, InvalidTaskError, RecoveryError, TransientTaskError
from .git_history import GitHistoryNormalizer, GitSnapshot, NormalizedHistory
from .process_supervision import capture_process_identity, terminate_process_group
from .store import TaskStore
from .security import redact_text


class CodexAdapter:
    def __init__(
        self,
        store: TaskStore,
        normalizer: GitHistoryNormalizer | None = None,
        *,
        heartbeat_interval_seconds: float = 30.0,
        termination_grace_seconds: float = 5.0,
    ) -> None:
        self.store = store
        self.normalizer = normalizer or GitHistoryNormalizer()
        self.heartbeat_interval_seconds = max(0.01, heartbeat_interval_seconds)
        self.termination_grace_seconds = max(0.0, termination_grace_seconds)

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
        findings = self.store.active_review_findings(task["task_id"])
        if findings:
            prompt += (
                "\n\nActive review findings for the current canonical commit. "
                "Address every requirement and preserve the prior commit as an ancestor:\n"
                + json.dumps(
                    [
                        {
                            "severity": item["severity"],
                            "file": item.get("file"),
                            "evidence": item["evidence"],
                            "requirement": item["requirement"],
                        }
                        for item in findings
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
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
        process: subprocess.Popen[str] | None = None
        child_pgid: int | None = None
        child_identity: dict[str, Any] | None = None
        stop_heartbeat = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(worktree).resolve()),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            child_pgid = os.getpgid(process.pid)
            child_identity = capture_process_identity(process.pid, child_pgid)
            if child_identity is None:
                self.store.start_unverified_agent_session(
                    session_id,
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                )
                terminated = terminate_process_group(
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                    grace_seconds=self.termination_grace_seconds,
                    process=process,
                )
                if terminated:
                    self.store.finish_agent_session(
                        session_id,
                        status="failed",
                        exit_code=None,
                        output_summary="Could not capture Codex child process identity",
                    )
                    raise ExternalCommandError(
                        "Codex child identity could not be captured; child was stopped"
                    )
                raise RecoveryError(
                    "Codex child identity could not be captured and exit is unconfirmed"
                )
            try:
                self.store.start_agent_session(
                    session_id,
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                    child_identity=child_identity,
                )
            except Exception:
                terminate_process_group(
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                    expected_identity=child_identity,
                    grace_seconds=self.termination_grace_seconds,
                    process=process,
                )
                raise

            def heartbeat() -> None:
                while not stop_heartbeat.wait(self.heartbeat_interval_seconds):
                    try:
                        self.store.heartbeat_agent_session(
                            session_id, task_id=task["task_id"]
                        )
                    except Exception:
                        # A later recovery pass treats a stale heartbeat together
                        # with the persisted process group; never spawn a duplicate.
                        continue

            heartbeat_thread = threading.Thread(
                target=heartbeat,
                name=f"brain-heartbeat-{session_id}",
                daemon=True,
            )
            heartbeat_thread.start()
            stdout, stderr = process.communicate(input=prompt, timeout=timeout)
        except FileNotFoundError as exc:
            self.store.finish_agent_session(
                session_id,
                status="failed",
                exit_code=None,
                output_summary=f"Command not found: {command[0]}",
            )
            raise ExternalCommandError(f"Command not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            assert process is not None
            terminated = terminate_process_group(
                child_pid=process.pid,
                child_pgid=child_pgid,
                expected_identity=child_identity,
                grace_seconds=self.termination_grace_seconds,
                process=process,
            )
            if not terminated:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                raise RecoveryError(
                    "Codex timed out and its process-group exit could not be confirmed; "
                    "the task will fail closed without a retry"
                ) from exc
            process.communicate(timeout=1)
            self.store.finish_agent_session(
                session_id,
                status="timed_out",
                exit_code=None,
                output_summary=(
                    f"Timed out after {timeout}s; process_group_terminated={terminated}"
                ),
            )
            raise TransientTaskError(f"Codex timed out after {timeout}s") from exc
        except (KeyboardInterrupt, SystemExit):
            if process is not None:
                terminated = terminate_process_group(
                    child_pid=process.pid,
                    child_pgid=child_pgid,
                    expected_identity=child_identity,
                    grace_seconds=self.termination_grace_seconds,
                    process=process,
                )
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                self.store.finish_agent_session(
                    session_id,
                    status="cancelled",
                    exit_code=None,
                    output_summary=f"Cancelled; process_group_terminated={terminated}",
                )
            raise
        finally:
            stop_heartbeat.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))
        assert process is not None
        summary = redact_text((stdout + "\n" + stderr).strip())[-4000:]
        self.store.finish_agent_session(
            session_id,
            status="completed" if process.returncode == 0 else "failed",
            exit_code=process.returncode,
            output_summary=summary,
        )
        if process.returncode != 0:
            raise ExternalCommandError(
                f"Codex failed with exit code {process.returncode}: {summary}",
                returncode=process.returncode,
            )
        message = task["payload"].get("commit_message") or f"feat: complete {task['task_id']}"
        if not isinstance(message, str) or not message.strip():
            raise InvalidTaskError("commit_message must be a non-empty string")
        return self.normalizer.normalize(worktree, snapshot, message=message)
