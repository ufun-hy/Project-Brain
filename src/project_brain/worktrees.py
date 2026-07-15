"""Isolated task worktree lifecycle with strict cleanup boundaries."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .commands import git
from .errors import ExternalCommandError, FetchError, InvalidPathError, WorktreeError
from .models import TERMINAL_STATUSES, TaskStatus
from .process_supervision import agent_process_group_alive, process_alive
from .repository import assert_registered_origin
from .runtime import RuntimePaths
from .store import TaskStore


def task_component(task_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-.")
    if not normalized:
        normalized = "task"
    if normalized != task_id or len(normalized) > 72:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized[:60]}-{digest}"
    return normalized


def task_branch(task_id: str) -> str:
    return f"brain/{task_component(task_id)}"


def heartbeat_age_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))


class WorktreeManager:
    def __init__(self, store: TaskStore, runtime: RuntimePaths) -> None:
        self.store = store
        self.runtime = runtime

    def create(self, task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        existing = self.store.get_worktree(task["task_id"])
        if existing and existing["status"] != "cleaned":
            path = self.validate_managed_path(project, existing["path"])
            if not path.exists():
                return self._recover_registered(task, project, existing, path)
            self._validate_existing(task, project, existing, path)
            self.store.heartbeat_worktree(task["task_id"], owner_pid=os.getpid())
            return self.store.get_worktree(task["task_id"]) or existing
        if existing and existing["status"] == "cleaned":
            path = self.validate_managed_path(project, existing["path"])
            return self._recover_registered(task, project, existing, path)

        repo = Path(project["repo_path"]).expanduser().resolve()
        if not (repo / ".git").exists():
            raise WorktreeError(f"Registered repository is missing: {repo}")
        assert_registered_origin(repo, project["remote_url"])
        default_branch = project["default_branch"]
        try:
            git(repo, "fetch", "--prune", "origin", default_branch, retryable=True)
        except ExternalCommandError as exc:
            raise FetchError(
                f"Unable to fetch origin/{default_branch} for {project['project_id']}: {exc}"
            ) from exc
        base_sha = git(
            repo, "rev-parse", f"refs/remotes/origin/{default_branch}"
        ).stdout.strip()
        branch = task_branch(task["task_id"])
        root = self._validated_root(project)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        path = self.validate_managed_path(project, root / task_component(task["task_id"]))
        if path.exists() or path.is_symlink():
            raise WorktreeError(f"Unregistered worktree path already exists: {path}")
        branch_exists = git(
            repo,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        ).returncode == 0
        if branch_exists:
            raise WorktreeError(f"Unregistered local task branch already exists: {branch}")
        remote_branch = git(
            repo,
            "ls-remote",
            "--heads",
            "origin",
            branch,
            check=False,
            retryable=True,
        )
        if remote_branch.returncode != 0:
            raise FetchError(f"Unable to inspect remote task branch: {branch}")
        if remote_branch.stdout.strip():
            raise WorktreeError(
                f"Remote task branch already exists and will not be overwritten: {branch}"
            )
        try:
            git(repo, "worktree", "add", "-b", branch, str(path), base_sha)
            os.chmod(path, 0o700)
        except Exception:
            if path.exists() and not any(path.iterdir()):
                path.rmdir()
            raise
        try:
            worktree = self.store.bind_worktree(
                task_id=task["task_id"],
                project_id=project["project_id"],
                path=str(path),
                branch=branch,
                base_sha=base_sha,
                owner_pid=os.getpid(),
            )
        except Exception:
            git(repo, "worktree", "remove", "--force", str(path), check=False)
            git(repo, "worktree", "prune", check=False)
            git(repo, "branch", "-D", branch, check=False)
            raise
        return worktree

    @staticmethod
    def _validate_existing(
        task: dict[str, Any],
        project: dict[str, Any],
        record: dict[str, Any],
        path: Path,
    ) -> None:
        assert_registered_origin(path, project["remote_url"])
        branch = git(path, "branch", "--show-current", check=False).stdout.strip()
        head = git(path, "rev-parse", "HEAD", check=False).stdout.strip()
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all", check=False).stdout
        conflicts = git(path, "diff", "--name-only", "--diff-filter=U", check=False).stdout
        expected = task.get("commit") or record["base_sha"]
        if branch != record["branch"] or head != expected or status or conflicts:
            raise WorktreeError(
                "Registered task worktree differs from its canonical branch, HEAD, or clean status"
            )

    def _recover_registered(
        self,
        task: dict[str, Any],
        project: dict[str, Any],
        record: dict[str, Any],
        path: Path,
    ) -> dict[str, Any]:
        branch = record["branch"]
        trusted_branch = task.get("branch")
        trusted_sha = task.get("commit") or task.get("head_sha")
        if trusted_branch != branch:
            raise WorktreeError("Remote recovery requires a registered branch and canonical commit")
        repo = Path(project["repo_path"]).expanduser().resolve()
        assert_registered_origin(repo, project["remote_url"])
        git(repo, "fetch", "origin", project["default_branch"], retryable=True)
        remote = git(repo, "ls-remote", "--heads", "origin", branch, retryable=True)
        fields = remote.stdout.strip().split()
        if trusted_sha and task.get("commit"):
            if len(fields) != 2 or fields[0] != trusted_sha:
                raise WorktreeError(
                    f"Registered remote branch does not match canonical commit: {branch}"
                )
            git(repo, "fetch", "origin", branch, retryable=True)
        elif fields:
            raise WorktreeError("Unpublished interrupted task unexpectedly has a remote branch")
        else:
            trusted_sha = record["base_sha"]
        if git(repo, "merge-base", "--is-ancestor", record["base_sha"], trusted_sha, check=False).returncode:
            raise WorktreeError("Remote task commit is not descended from its registered base")
        git(repo, "worktree", "prune")
        if path.exists() or path.is_symlink():
            raise WorktreeError(f"Registered recovery path is occupied: {path}")
        local_ref = f"refs/heads/{branch}"
        if git(repo, "show-ref", "--verify", "--quiet", local_ref, check=False).returncode == 0:
            local_sha = git(repo, "rev-parse", local_ref).stdout.strip()
            if local_sha != trusted_sha:
                raise WorktreeError("Registered local task branch differs from canonical commit")
            git(repo, "worktree", "add", str(path), branch)
        else:
            git(repo, "worktree", "add", "-b", branch, str(path), trusted_sha)
        os.chmod(path, 0o700)
        worktree = self.store.bind_worktree(
            task_id=task["task_id"],
            project_id=project["project_id"],
            path=str(path),
            branch=branch,
            base_sha=record["base_sha"],
            owner_pid=os.getpid(),
        )
        self.store.set_task_fields(
            task["task_id"],
            head_sha=trusted_sha,
            **({"commit": trusted_sha} if task.get("commit") else {}),
        )
        self.store.record_event(
            task_id=task["task_id"],
            event_type="worktree_recovered_from_remote",
            payload={"branch": branch, "head_sha": trusted_sha},
        )
        return worktree

    def validate_managed_path(self, project: dict[str, Any], candidate: str | Path) -> Path:
        root = Path(project["worktree_root"]).expanduser().resolve()
        expected_root = self.runtime.project_worktree_root(project["project_id"]).resolve()
        runtime_root = self.runtime.worktrees_dir.resolve()
        if root != expected_root or runtime_root not in root.parents:
            raise InvalidPathError(
                f"Configured worktree root is outside managed runtime: {root}"
            )
        repo = Path(project["repo_path"]).expanduser().resolve()
        if root == repo or root in repo.parents or repo in root.parents:
            raise InvalidPathError(
                f"Configured worktree root overlaps registered checkout: root={root} repo={repo}"
            )
        path = Path(candidate).expanduser().resolve()
        if path == root or root not in path.parents:
            raise InvalidPathError(
                f"Refusing path outside configured worktree root: {path} (root: {root})"
            )
        return path

    def _validated_root(self, project: dict[str, Any]) -> Path:
        root = Path(project["worktree_root"]).expanduser().resolve()
        # Reuse the same overlap check with a guaranteed child candidate.
        self.validate_managed_path(project, root / ".boundary-check")
        return root

    def cleanup_task(
        self,
        task_id: str,
        *,
        dry_run: bool = True,
        forensic_archive_id: int | None = None,
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        project = self.store.get_project(task["project_id"])
        record = self.store.get_worktree(task_id)
        if not record:
            raise WorktreeError(f"Task has no registered worktree: {task_id}")
        path = self.validate_managed_path(project, record["path"])
        if record["status"] == "cleaned":
            return {"task_id": task_id, "path": str(path), "action": "already_cleaned"}
        status = TaskStatus(task["status"])
        if status not in TERMINAL_STATUSES:
            raise WorktreeError(
                f"Active/reviewable task worktree is retained: {task_id} ({status.value})"
            )
        owner_pid = record.get("owner_pid")
        heartbeat_age = heartbeat_age_seconds(record.get("heartbeat_at"))
        if owner_pid != os.getpid() and process_alive(owner_pid):
            raise WorktreeError(
                f"Worktree owner process is still alive: task={task_id} pid={owner_pid} "
                f"heartbeat_age_seconds={heartbeat_age}"
            )
        if not owner_pid and heartbeat_age is not None and heartbeat_age < 300:
            raise WorktreeError(
                f"Worktree has no owner PID but its heartbeat is recent: task={task_id} "
                f"heartbeat_age_seconds={heartbeat_age}"
            )
        session_id = task.get("agent_session_id")
        session = self.store.get_agent_session(session_id) if session_id else None
        session_is_active = bool(
            session
            and session.get("status") in {"starting", "running", "recovery_blocked"}
        )
        child_group_alive = bool(
            session
            and session.get("child_pid")
            and agent_process_group_alive(
                session.get("child_pid"), session.get("child_pgid")
            )
        )
        if session and (
            (session_is_active and not session.get("child_pid")) or child_group_alive
        ):
            raise WorktreeError(
                f"Persisted Codex process group prevents cleanup: task={task_id} "
                f"pid={session.get('child_pid')} pgid={session.get('child_pgid')}"
            )
        result = {
            "task_id": task_id,
            "project_id": task["project_id"],
            "path": str(path),
            "branch": record["branch"],
            "owner_pid": owner_pid,
            "heartbeat_age_seconds": heartbeat_age,
            "action": "would_clean" if dry_run else "cleaned",
        }
        if dry_run:
            return result
        if forensic_archive_id is None:
            raise WorktreeError(
                f"Cleanup requires a persisted forensic archive: {task_id}"
            )
        archive = self.store.get_forensic_archive_by_id(forensic_archive_id)
        if (
            archive["task_id"] != task_id
            or archive["worktree_id"] != record["worktree_id"]
        ):
            raise WorktreeError("Forensic archive does not match the terminal worktree")
        repo = Path(project["repo_path"]).expanduser().resolve()
        if path.exists() or path.is_symlink():
            git(repo, "worktree", "remove", "--force", str(path))
        git(repo, "worktree", "prune")
        if git(
            repo,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{record['branch']}",
            check=False,
        ).returncode == 0:
            git(repo, "branch", "-D", record["branch"])
        self.store.mark_worktree_cleaned(task_id)
        self.store.record_event(
            task_id=task_id,
            event_type="worktree_cleaned",
            payload={
                "path": str(path),
                "branch": record["branch"],
                "forensic_archive_id": forensic_archive_id,
            },
        )
        return result

    def release_review_worktree(self, task_id: str) -> dict[str, Any]:
        """Release a safely published review worktree while retaining remote history."""
        task = self.store.get_task(task_id)
        if task["status"] != TaskStatus.AWAITING_REVIEW.value:
            raise WorktreeError(f"Task is not awaiting review: {task_id}")
        project = self.store.get_project(task["project_id"])
        if not project.get("auto_push"):
            raise WorktreeError("Unpublished task worktrees cannot be released")
        if project.get("auto_pr") and not task.get("pr_url"):
            raise WorktreeError("Task worktree cannot be released before Draft PR creation")
        record = self.store.get_worktree(task_id)
        if not record or record["status"] == "cleaned":
            return {"task_id": task_id, "action": "already_released"}
        path = self.validate_managed_path(project, record["path"])
        branch = git(path, "branch", "--show-current").stdout.strip()
        head = git(path, "rev-parse", "HEAD").stdout.strip()
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout
        if branch != record["branch"] or head != task.get("commit") or status:
            raise WorktreeError("Published review worktree is not clean at its canonical commit")
        remote = git(path, "ls-remote", "--heads", "origin", branch, retryable=True)
        fields = remote.stdout.strip().split()
        if len(fields) != 2 or fields[0] != head:
            raise WorktreeError("Remote review branch does not match the canonical commit")
        repo = Path(project["repo_path"]).expanduser().resolve()
        git(repo, "worktree", "remove", str(path))
        git(repo, "worktree", "prune")
        git(repo, "branch", "-D", branch)
        self.store.mark_worktree_cleaned(task_id)
        self.store.set_task_fields(task_id, worktree_path=None)
        self.store.record_event(
            task_id=task_id,
            event_type="review_worktree_released",
            payload={"branch": branch, "head_sha": head},
        )
        return {"task_id": task_id, "action": "released", "branch": branch, "head_sha": head}
