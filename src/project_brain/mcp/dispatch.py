"""Fixed-argv asynchronous dispatcher for one-shot Core workers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from project_brain.errors import InvalidTaskError
from project_brain.locking import RuntimeLock
from project_brain.models import CLAIMABLE_STATUSES, parse_timestamp, utc_now
from project_brain.recovery import RecoveryManager, RecoveryReport
from project_brain.runtime import RuntimePaths
from project_brain.security import contains_known_secret, redact_text
from project_brain.store import TaskStore
from project_brain.worktrees import WorktreeManager


WORKER_ENV_ALLOWLIST = {
    "CODEX_HOME",
    "GH_HOST",
    "GH_TOKEN",
    "GITHUB_HOST",
    "GITHUB_TOKEN",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "NO_PROXY",
    "OPENAI_API_KEY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSH_AUTH_SOCK",
    "SSL_CERT_FILE",
    "TERM",
    "TMPDIR",
    "USER",
    "XDG_CONFIG_HOME",
}


def fixed_worker_environment(source: Mapping[str, str], runtime: RuntimePaths) -> dict[str, str]:
    """Build the non-request-configurable environment used by dispatch workers."""
    environment = {key: source[key] for key in WORKER_ENV_ALLOWLIST if source.get(key)}
    environment.update(
        {
            "PROJECT_BRAIN_JSON_LINES": "1",
            "PROJECT_BRAIN_RUNTIME_ROOT": str(runtime.root),
            "PROJECT_BRAIN_WORKER_OUTPUT": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment


class OneShotDispatcher:
    """Preflight claim safety and start one fixed Core worker without waiting."""

    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimePaths,
        *,
        python_executable: str | None = None,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.python_executable = str(Path(python_executable or sys.executable).resolve())
        self.popen_factory = popen_factory
        self.environment = fixed_worker_environment(
            environment if environment is not None else os.environ,
            runtime,
        )
        self.worker_cwd = Path(__file__).resolve().parents[2]
        self._dispatch_lock = threading.Lock()
        self._active_process: subprocess.Popen[Any] | None = None

    @property
    def worker_argv(self) -> list[str]:
        return [
            self.python_executable,
            "-m",
            "project_brain",
            "--runtime-root",
            str(self.runtime.root),
            "apply",
            "--json",
        ]

    def dispatch(self, *, reason: str | None = None) -> dict[str, Any]:
        if reason is not None:
            if not isinstance(reason, str) or not reason.strip():
                raise InvalidTaskError("dispatch reason must be a non-empty string")
            if len(reason) > 500:
                raise InvalidTaskError("dispatch reason must be at most 500 characters")
            if contains_known_secret(reason):
                raise InvalidTaskError("dispatch reason contains a credential-like value")
        safe_reason = redact_text(reason.strip()) if reason else None
        with self._dispatch_lock:
            if self._active_process is not None and self._active_process.poll() is None:
                return self._result(
                    "already_running",
                    claim_safe=False,
                    reason="A worker launched by this MCP server is still running",
                    audit_reason=safe_reason,
                )
            if not RuntimeLock.probe_available(self.runtime.lock_file):
                return self._result(
                    "already_running",
                    claim_safe=False,
                    reason="The Project Brain runtime lock is held",
                    audit_reason=safe_reason,
                )
            preview = RecoveryManager(
                self.store, WorktreeManager(self.store, self.runtime)
            ).preview_for_dispatch()
            if not preview.claim_safe:
                return self._result(
                    "blocked",
                    claim_safe=False,
                    blockers=preview.claim_blockers,
                    reason="Recovery or agent identity requires operator attention",
                    audit_reason=safe_reason,
                )
            if not self._has_dispatchable_work(preview):
                return self._result(
                    "idle",
                    claim_safe=True,
                    reason="No task is ready for a one-shot worker",
                    audit_reason=safe_reason,
                )
            log_id, handle = self._open_log(safe_reason)
            try:
                self._audit("launch_requested", reason=safe_reason, log_id=log_id)
            except Exception:
                handle.close()
                raise
            try:
                process = self.popen_factory(
                    self.worker_argv,
                    cwd=str(self.worker_cwd),
                    env=dict(self.environment),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    start_new_session=True,
                )
            except Exception as exc:
                handle.write(
                    json.dumps(
                        {
                            "event": "dispatch_failed",
                            "created_at": utc_now(),
                            "error": redact_text(str(exc))[:1_000],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()
                handle.close()
                self._audit(
                    "failed", reason=safe_reason, log_id=log_id, error=redact_text(str(exc))
                )
                return {
                    "dispatch_status": "failed",
                    "code": "internal",
                    "message": "The fixed one-shot worker could not be started",
                    "worker_pid": None,
                    "log_id": log_id,
                    "claim_safety": {"claim_safe": True, "blockers": []},
                    "next_action": "Inspect the private dispatch log and local Core health.",
                }
            finally:
                if not handle.closed:
                    handle.close()
            self._active_process = process
            return {
                "dispatch_status": "started",
                "code": "ok",
                "message": "One fixed Core worker was started asynchronously",
                "worker_pid": process.pid,
                "log_id": log_id,
                "claim_safety": {"claim_safe": True, "blockers": []},
                "next_action": "Poll project_brain_tasks_get or project_brain_tasks_list.",
            }

    def _has_dispatchable_work(self, preview: RecoveryReport) -> bool:
        if any(item.get("action") == "would_recover" for item in preview.actions):
            return True
        now = datetime.now(timezone.utc)
        claimable = {status.value for status in CLAIMABLE_STATUSES}
        for task in self.store.list_tasks(limit=1000):
            if task["status"] not in claimable:
                continue
            expiry = parse_timestamp(task.get("expires_at"))
            if expiry is None or expiry > now:
                return True
        return False

    def _open_log(self, reason: str | None) -> tuple[str, Any]:
        directory = self.runtime.logs_dir / "mcp-dispatch"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        log_id = f"dispatch-{timestamp}-{uuid.uuid4().hex[:12]}.jsonl"
        path = directory / log_id
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.chmod(path, 0o600)
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        handle.write(
            json.dumps(
                {
                    "event": "dispatch_requested",
                    "created_at": utc_now(),
                    "reason": reason,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        handle.flush()
        return log_id, handle

    def _result(
        self,
        dispatch_status: str,
        *,
        claim_safe: bool,
        reason: str,
        audit_reason: str | None,
        blockers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        safe_blockers = [
            {
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "attempt_count": item.get("attempt_count"),
                "reason": redact_text(str(item.get("reason") or ""))[:1_000] or None,
            }
            for item in (blockers or [])[:20]
        ]
        self._audit(
            dispatch_status,
            reason=audit_reason,
            blockers=[item["task_id"] for item in safe_blockers],
        )
        code = "recovery_blocked" if dispatch_status == "blocked" else dispatch_status
        return {
            "dispatch_status": dispatch_status,
            "code": code,
            "message": redact_text(reason)[:1_000],
            "worker_pid": None,
            "log_id": None,
            "claim_safety": {"claim_safe": claim_safe, "blockers": safe_blockers},
            "next_action": (
                "Use project_brain_tasks_recovery_preview and the local recovery CLI."
                if dispatch_status == "blocked"
                else "Poll again after the active worker exits."
                if dispatch_status == "already_running"
                else "Create a task before dispatching."
            ),
        }

    def _audit(self, dispatch_status: str, **payload: Any) -> None:
        safe_payload = {
            key: redact_text(str(value))[:1_000] if isinstance(value, str) else value
            for key, value in payload.items()
            if value is not None
        }
        self.store.record_event(
            task_id=None,
            event_type="mcp_dispatch_requested",
            payload={"dispatch_status": dispatch_status, **safe_payload},
        )
