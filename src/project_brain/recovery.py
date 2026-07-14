"""Deterministic reconciliation for interrupted task attempts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .commands import git
from .errors import InvalidPathError, WorktreeError
from .models import AttemptPhase, TaskStatus
from .process_supervision import agent_process_group_alive, terminate_process_group
from .repository import assert_registered_origin
from .store import TaskStore
from .worktrees import WorktreeManager, heartbeat_age_seconds, process_alive


class RecoveryManager:
    def __init__(
        self,
        store: TaskStore,
        worktrees: WorktreeManager,
        *,
        termination_grace_seconds: float = 5.0,
    ) -> None:
        self.store = store
        self.worktrees = worktrees
        self.termination_grace_seconds = max(0.0, termination_grace_seconds)

    def reconcile(
        self,
        task_id: str | None = None,
        *,
        execute: bool = False,
        terminate_agent: bool = False,
    ) -> list[dict[str, Any]]:
        tasks = (
            [self.store.get_task(task_id)]
            if task_id
            else self.store.list_tasks(status=TaskStatus.RUNNING.value, limit=1000)
        )
        results: list[dict[str, Any]] = []
        for task in tasks:
            if task["status"] != TaskStatus.RUNNING.value:
                results.append(
                    {
                        "task_id": task["task_id"],
                        "action": "unchanged",
                        "reason": f"task status is {task['status']}",
                    }
                )
                continue
            results.append(
                self._reconcile_one(
                    task,
                    execute=execute,
                    terminate_agent=terminate_agent,
                )
            )
        return results

    def _reconcile_one(
        self,
        task: dict[str, Any],
        *,
        execute: bool,
        terminate_agent: bool,
    ) -> dict[str, Any]:
        record = self.store.get_worktree(task["task_id"])
        session = self.store.active_agent_session(task["task_id"])
        if session:
            child_pid = session.get("child_pid")
            child_pgid = session.get("child_pgid")
            if not child_pid:
                return {
                    "task_id": task["task_id"],
                    "action": "unchanged",
                    "reason": (
                        "agent startup was interrupted before child PID persistence; "
                        "automatic recovery cannot prove that no child is running"
                    ),
                }
            if agent_process_group_alive(child_pid, child_pgid):
                if not (execute and terminate_agent):
                    return {
                        "task_id": task["task_id"],
                        "action": "unchanged",
                        "reason": (
                            "persisted Codex process group is still alive; recovery will not "
                            f"start another attempt (pid={child_pid} pgid={child_pgid})"
                        ),
                    }
                terminated = terminate_process_group(
                    child_pid=child_pid,
                    child_pgid=child_pgid,
                    grace_seconds=self.termination_grace_seconds,
                )
                if not terminated:
                    return {
                        "task_id": task["task_id"],
                        "action": "unchanged",
                        "reason": (
                            "explicit recovery could not confirm Codex process-group exit; "
                            "no new attempt will start"
                        ),
                    }
                self.store.finish_agent_session(
                    session["session_id"],
                    status="interrupted",
                    exit_code=None,
                    output_summary="Explicit recovery terminated the Codex process group",
                )
        heartbeat_age = heartbeat_age_seconds(record.get("heartbeat_at")) if record else None
        if (
            record
            and process_alive(record.get("owner_pid"))
            and heartbeat_age is not None
            and heartbeat_age <= 3600
        ):
            return {
                "task_id": task["task_id"],
                "action": "unchanged",
                "reason": (
                    f"owner PID {record['owner_pid']} is alive; "
                    f"heartbeat_age_seconds={heartbeat_age}"
                ),
            }
        target, reason = self._classify(task, record)
        result = {
            "task_id": task["task_id"],
            "phase": task["attempt_phase"],
            "from_status": task["status"],
            "to_status": target.value,
            "action": "recovered" if execute else "would_recover",
            "reason": reason,
        }
        if execute:
            self.store.recover_running_task(
                task["task_id"], target=target, reason=reason
            )
        return result

    def _classify(
        self,
        task: dict[str, Any],
        record: dict[str, Any] | None,
    ) -> tuple[TaskStatus, str]:
        phase = AttemptPhase(task["attempt_phase"])
        if record is None:
            return TaskStatus.FAILED, "Interrupted task has no registered worktree"
        try:
            project = self.store.get_project(task["project_id"])
            path = self.worktrees.validate_managed_path(project, record["path"])
            assert_registered_origin(project["repo_path"], project["remote_url"])
        except (InvalidPathError, WorktreeError) as exc:
            return TaskStatus.FAILED, f"Unsafe interrupted worktree metadata: {exc}"
        if not path.exists():
            if phase is AttemptPhase.REVIEW and task.get("commit"):
                remote = git(
                    project["repo_path"],
                    "ls-remote",
                    "--heads",
                    "origin",
                    record["branch"],
                    check=False,
                ).stdout.strip().split()
                if len(remote) == 2 and remote[0] == task["commit"]:
                    return (
                        TaskStatus.AWAITING_REVIEW,
                        "Published canonical commit is intact on the registered remote",
                    )
            if task.get("branch") == record["branch"] and (
                task.get("commit") or phase is AttemptPhase.IMPLEMENTATION
            ):
                return (
                    TaskStatus.RETRY_PENDING,
                    "Interrupted registered worktree is missing and will be reconstructed",
                )
            return TaskStatus.FAILED, "Interrupted worktree is missing without recoverable Git state"
        branch = git(path, "branch", "--show-current", check=False).stdout.strip()
        head = git(path, "rev-parse", "HEAD", check=False).stdout.strip()
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all", check=False).stdout
        conflicts = git(path, "diff", "--name-only", "--diff-filter=U", check=False).stdout
        expected = task.get("commit") or record["base_sha"]
        if branch != record["branch"] or head != expected or status or conflicts:
            return (
                TaskStatus.FAILED,
                "Interrupted worktree has branch, HEAD, file, or conflict mutations; "
                "forensic archival is required before cleanup",
            )
        if phase is AttemptPhase.REVIEW:
            return TaskStatus.AWAITING_REVIEW, "Review publication completed before interruption"
        return TaskStatus.RETRY_PENDING, f"Clean interrupted {phase.value} phase can be retried"
