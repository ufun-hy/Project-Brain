"""Shared read models for CLI and controlled adapters."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .locking import RuntimeLock
from .executables import find_executable
from .models import TaskStatus, parse_timestamp
from .runtime import RuntimePaths
from .security import redact_text
from .store import SCHEMA_VERSION, TaskStore
from .project_config import executable_available

NEXT_ACTION = {
    TaskStatus.PENDING.value: "Run project-brain apply.",
    TaskStatus.RUNNING.value: "Wait for the active process; inspect health if its deadline expires.",
    TaskStatus.RECOVERY_BLOCKED.value: (
        "Inspect agent identity, then use tasks recover with an explicit operator resolution."
    ),
    TaskStatus.RETRY_PENDING.value: "Retry from a new apply process after the transient issue clears.",
    TaskStatus.VERIFICATION_FAILED.value: "Inspect verification evidence, then request changes.",
    TaskStatus.NEEDS_CHANGES.value: "Run project-brain apply for the requested revision work.",
    TaskStatus.AWAITING_REVIEW.value: "Review evidence and the Draft PR; do not merge automatically.",
    TaskStatus.READY_TO_MERGE.value: "Await explicit user merge authorization.",
    TaskStatus.MERGING.value: "Wait for the authorized merge operation.",
    TaskStatus.ACCEPTED.value: "No automatic action; terminal accepted task.",
    TaskStatus.COMPLETED.value: "Review the completed local analysis result.",
    TaskStatus.MERGE_FAILED.value: "Inspect merge failure and choose retry or needs_changes.",
    TaskStatus.FAILED.value: "Inspect the permanent error; create a new revision if needed.",
    TaskStatus.SUPERSEDED.value: "Follow the replacement task revision.",
    TaskStatus.EXPIRED.value: "Create a new task or revision with a valid expiry.",
}


def task_view(
    task: dict[str, Any], projects: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Add derived, source-neutral fields to a stored task."""
    updated = parse_timestamp(task.get("updated_at"))
    elapsed = None
    if updated:
        elapsed = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
    safe_task = {
        key: value
        for key, value in task.items()
        if key not in {"execution_profile", "payload"}
    }
    return {
        **safe_task,
        "project": projects.get(task["project_id"], {}).get("name", task["project_id"]),
        "elapsed_seconds": elapsed,
        "next_action": NEXT_ACTION.get(task["status"], "Inspect task state."),
    }


def status_report(store: TaskStore, *, limit: int = 100) -> dict[str, Any]:
    """Return the task status report used by CLI and adapters."""
    projects = {item["project_id"]: item for item in store.list_projects()}
    tasks = [task_view(task, projects) for task in store.list_tasks(limit=limit)]
    return {
        "status": "ok",
        "counts": dict(sorted(Counter(task["status"] for task in tasks).items())),
        "tasks": tasks,
    }


def health_report(store: TaskStore, runtime: RuntimePaths) -> dict[str, Any]:
    """Check runtime, executable, and registered-project prerequisites."""
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {"name": name, "status": "passed" if passed else "failed", "detail": detail}
        )

    check(
        "runtime_root",
        runtime.root.is_dir() and os.access(runtime.root, os.W_OK),
        str(runtime.root),
    )
    check(
        "database_schema",
        store.schema_version() == SCHEMA_VERSION,
        f"version={store.schema_version()} expected={SCHEMA_VERSION}",
    )
    lock_available = RuntimeLock.probe_available(runtime.lock_file)
    check(
        "runtime_lock",
        lock_available,
        "available" if lock_available else "held by another process",
    )
    git = find_executable("git")
    gh = find_executable("gh")
    check("git", git is not None, git or "not found")
    check("gh", gh is not None, gh or "not found")
    for project in store.list_projects():
        repo = Path(project["repo_path"])
        check(
            f"project:{project['project_id']}",
            repo.exists() and (repo / ".git").exists(),
            str(repo),
        )
        executable = (
            project.get("codex_command", [""])[0]
            if project.get("codex_command")
            else ""
        )
        available = bool(executable) and executable_available(executable)
        check(
            f"codex:{project['project_id']}",
            available,
            executable or "not configured",
        )
    return {
        "status": (
            "healthy"
            if all(item["status"] == "passed" for item in checks)
            else "unhealthy"
        ),
        "checks": checks,
    }


def worker_result_view(value: dict[str, Any]) -> dict[str, Any]:
    """Bound dispatcher worker output without returning task payloads or commands."""
    task = value.get("task") if isinstance(value.get("task"), dict) else None
    safe: dict[str, Any] = {
        "status": redact_text(str(value.get("status") or "unknown"))[:128],
        "claim_safe": bool(value.get("claim_safe", True)),
    }
    if task:
        safe["task"] = {
            "task_id": task.get("task_id"),
            "project_id": task.get("project_id"),
            "status": task.get("status"),
            "attempt_phase": task.get("attempt_phase"),
            "attempt_count": task.get("attempt_count"),
            "commit": task.get("commit"),
            "pr_url": task.get("pr_url"),
            "last_error": redact_text(str(task.get("last_error") or ""))[:2000] or None,
        }
    blockers = value.get("claim_blockers")
    if isinstance(blockers, list):
        safe["claim_blockers"] = [
            {
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "reason": redact_text(str(item.get("reason") or ""))[:1000] or None,
            }
            for item in blockers[:20]
            if isinstance(item, dict)
        ]
    return safe
