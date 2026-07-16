"""Deterministic reconciliation for interrupted task attempts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .commands import git
from .errors import InvalidPathError, InvalidTaskError, WorktreeError
from .models import AttemptPhase, TaskStatus
from .process_supervision import (
    ProcessIdentityState,
    inspect_agent_process_group,
    terminate_process_group,
)
from .repository import assert_registered_origin
from .store import TaskStore
from .worktrees import WorktreeManager, heartbeat_age_seconds, process_alive


@dataclass(frozen=True)
class RecoveryReport:
    actions: list[dict[str, Any]]
    claim_blockers: list[dict[str, Any]]

    @property
    def claim_safe(self) -> bool:
        return not self.claim_blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_safe": self.claim_safe,
            "claim_blockers": self.claim_blockers,
            "recovery_actions": self.actions,
        }


class RecoveryManager:
    def __init__(
        self,
        store: TaskStore,
        worktrees: WorktreeManager,
        *,
        termination_grace_seconds: float = 5.0,
        ambiguous_startup_grace_seconds: float = 300.0,
    ) -> None:
        self.store = store
        self.worktrees = worktrees
        self.termination_grace_seconds = max(0.0, termination_grace_seconds)
        self.ambiguous_startup_grace_seconds = max(
            0.0, ambiguous_startup_grace_seconds
        )

    def reconcile(
        self,
        task_id: str | None = None,
        *,
        execute: bool = False,
        terminate_agent: bool = False,
        confirm_no_agent: bool = False,
        resume: bool = False,
        cancel: bool = False,
    ) -> list[dict[str, Any]]:
        tasks = (
            [self.store.get_task(task_id)]
            if task_id
            else self.store.list_tasks(status=TaskStatus.RUNNING.value, limit=1000)
        )
        results: list[dict[str, Any]] = []
        for task in tasks:
            if task["status"] == TaskStatus.RECOVERY_BLOCKED.value:
                results.append(
                    self._resolve_blocked(
                        task,
                        execute=execute,
                        confirm_no_agent=confirm_no_agent,
                        resume=resume,
                        cancel=cancel,
                    )
                )
                continue
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

    def reconcile_for_claims(self, *, execute: bool) -> RecoveryReport:
        """Reconcile interrupted work, then expose the global single-agent gate."""
        actions = self.reconcile(execute=execute)
        action_by_task = {item["task_id"]: item for item in actions}
        blockers: list[dict[str, Any]] = []
        for task in self.store.list_claim_blocking_tasks():
            action = action_by_task.get(task["task_id"], {})
            blockers.append(
                {
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "attempt_count": task["attempt_count"],
                    "agent_session_id": task.get("agent_session_id"),
                    "reason": action.get("reason") or task.get("last_error"),
                }
            )
        return RecoveryReport(actions=actions, claim_blockers=blockers)

    def preview_for_dispatch(self) -> RecoveryReport:
        """Preview whether a one-shot worker may safely run without changing state.

        A clean interrupted task reported as ``would_recover`` is safe for the
        worker because the worker performs that recovery under RuntimeLock before
        claiming. Live, ambiguous, and operator-blocked agent state remains a
        dispatch blocker.
        """
        actions = self.reconcile(execute=False)
        action_by_task = {item["task_id"]: item for item in actions}
        blockers: list[dict[str, Any]] = []
        for task in self.store.list_claim_blocking_tasks():
            action = action_by_task.get(task["task_id"], {})
            if (
                task["status"] == TaskStatus.RUNNING.value
                and action.get("action") == "would_recover"
            ):
                continue
            blockers.append(
                {
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "attempt_count": task["attempt_count"],
                    "agent_session_id": task.get("agent_session_id"),
                    "reason": action.get("reason") or task.get("last_error"),
                }
            )
        return RecoveryReport(actions=actions, claim_blockers=blockers)

    def agent_identity_preview(self, task_id: str) -> dict[str, Any]:
        """Return bounded process-identity state without commands or raw identity."""
        task = self.store.get_task(task_id)
        session = self.store.active_agent_session(task_id)
        if session is None and task.get("agent_session_id"):
            try:
                session = self.store.get_agent_session(task["agent_session_id"])
            except InvalidTaskError:
                session = None
        if session is None:
            return {
                "session_present": False,
                "session_status": None,
                "child_pid_present": False,
                "child_pgid_present": False,
                "identity_state": "none",
            }
        child_pid = session.get("child_pid")
        child_pgid = session.get("child_pgid")
        if not child_pid:
            state = "starting" if session.get("status") == "starting" else "not_running"
        elif session.get("status") == TaskStatus.RECOVERY_BLOCKED.value:
            state = "operator_resolution_required"
        else:
            state = inspect_agent_process_group(
                child_pid, child_pgid, session.get("child_identity")
            ).value
        return {
            "session_present": True,
            "session_status": session.get("status"),
            "child_pid_present": bool(child_pid),
            "child_pgid_present": bool(child_pgid),
            "identity_state": state,
        }

    def _resolve_blocked(
        self,
        task: dict[str, Any],
        *,
        execute: bool,
        confirm_no_agent: bool,
        resume: bool,
        cancel: bool,
    ) -> dict[str, Any]:
        selected = sum((confirm_no_agent, resume, cancel))
        if selected > 1:
            return {
                "task_id": task["task_id"],
                "action": "unchanged",
                "reason": "choose only one recovery-block resolution",
            }
        if not selected:
            return {
                "task_id": task["task_id"],
                "action": "unchanged",
                "reason": (
                    "operator resolution required: confirm no matching agent is running, "
                    "resume after inspection, or cancel the task"
                ),
            }
        resolution = "cancel" if cancel else ("resume" if resume else "confirm_no_agent")
        target = TaskStatus.FAILED if cancel else TaskStatus.RETRY_PENDING
        result = {
            "task_id": task["task_id"],
            "from_status": TaskStatus.RECOVERY_BLOCKED.value,
            "to_status": target.value,
            "action": "recovery_resolved" if execute else "would_resolve_recovery",
            "resolution": resolution,
        }
        if execute:
            self.store.resolve_recovery_block(task["task_id"], resolution=resolution)
        return result

    def _block(
        self,
        task: dict[str, Any],
        *,
        execute: bool,
        reason: str,
    ) -> dict[str, Any]:
        result = {
            "task_id": task["task_id"],
            "phase": task["attempt_phase"],
            "from_status": TaskStatus.RUNNING.value,
            "to_status": TaskStatus.RECOVERY_BLOCKED.value,
            "action": "recovery_blocked" if execute else "would_recovery_block",
            "reason": reason,
        }
        if execute:
            self.store.block_running_task(task["task_id"], reason=reason)
        return result

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
                age = heartbeat_age_seconds(
                    session.get("heartbeat_at") or session.get("started_at")
                )
                if age is not None and age < self.ambiguous_startup_grace_seconds:
                    return {
                        "task_id": task["task_id"],
                        "action": "unchanged",
                        "reason": (
                            "agent startup has no persisted child PID and remains within "
                            f"the {self.ambiguous_startup_grace_seconds:g}s grace period"
                        ),
                    }
                return self._block(
                    task,
                    execute=execute,
                    reason=(
                        "agent startup exceeded its grace period without child PID "
                        "persistence; operator confirmation is required before retry"
                    ),
                )
            identity = session.get("child_identity")
            process_state = inspect_agent_process_group(child_pid, child_pgid, identity)
            if process_state is ProcessIdentityState.UNVERIFIED_ALIVE:
                return self._block(
                    task,
                    execute=execute,
                    reason=(
                        "persisted Codex PID/PGID is alive but its process identity cannot "
                        "be proven; no signal was sent"
                    ),
                )
            if process_state is ProcessIdentityState.VERIFIED_ALIVE:
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
                    expected_identity=identity,
                    grace_seconds=self.termination_grace_seconds,
                )
                if not terminated:
                    return self._block(
                        task,
                        execute=execute,
                        reason=(
                            "explicit recovery could not re-verify and terminate the Codex "
                            "process identity; no new attempt will start"
                        ),
                    )
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
            project = self.store.task_execution_profile(task)
            path = self.worktrees.validate_managed_path(project, record["path"])
            assert_registered_origin(project["repo_path"], project["remote_url"])
        except (InvalidPathError, InvalidTaskError, WorktreeError) as exc:
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
