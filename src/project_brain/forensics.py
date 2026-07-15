"""Immutable terminal-worktree evidence and archive-gated cleanup."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .commands import git
from .errors import InvalidPathError, WorktreeError
from .models import TERMINAL_STATUSES, TaskStatus
from .runtime import RuntimePaths
from .store import TaskStore
from .worktrees import WorktreeManager


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    mode = "wb" if isinstance(data, bytes) else "w"
    kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
    with os.fdopen(descriptor, mode, **kwargs) as stream:
        stream.write(data)
    os.chmod(path, 0o600)


class FailureForensics:
    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimePaths,
        worktrees: WorktreeManager,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.worktrees = worktrees

    def capture(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if TaskStatus(task["status"]) not in TERMINAL_STATUSES:
            raise WorktreeError(f"Forensics require a terminal task: {task_id}")
        record = self.store.get_worktree(task_id)
        if record is None:
            raise WorktreeError(f"Task has no registered worktree: {task_id}")
        project = self.store.get_project(task["project_id"])
        worktree = self.worktrees.validate_managed_path(project, record["path"])
        target = self.runtime.forensic_archive_dir(
            task_id, worktree_id=int(record["worktree_id"])
        )

        existing = self.store.get_forensic_archive(task_id)
        if existing is not None:
            self._verify_existing(existing, target)
            return existing

        if target.exists():
            return self._adopt_complete_archive(task_id, record, target)

        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        target.mkdir(mode=0o700)
        os.chmod(target, 0o700)
        self._capture_files(task, record, worktree, target)
        manifest_entries: list[dict[str, Any]] = []
        for artifact in sorted(target.rglob("*")):
            if not artifact.is_file() or artifact.name == "manifest.json":
                continue
            manifest_entries.append(
                {
                    "path": str(artifact.relative_to(target)),
                    "sha256": _sha256(artifact),
                    "size": artifact.stat().st_size,
                }
            )
        manifest = {
            "task_id": task_id,
            "worktree_id": record["worktree_id"],
            "files": manifest_entries,
        }
        manifest_path = target / "manifest.json"
        _write_private(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return self.store.record_forensic_archive(
            task_id=task_id,
            worktree_id=int(record["worktree_id"]),
            artifact_path=str(target),
            manifest_sha256=_sha256(manifest_path),
        )

    def _capture_files(
        self,
        task: dict[str, Any],
        record: dict[str, Any],
        worktree: Path,
        target: Path,
    ) -> None:
        metadata = {
            "task_id": task["task_id"],
            "project_id": task["project_id"],
            "task_status": task["status"],
            "attempt_count": task["attempt_count"],
            "attempt_phase": task["attempt_phase"],
            "canonical_head_sha": task.get("commit"),
            "last_error": task.get("last_error"),
            "worktree_id": record["worktree_id"],
            "worktree_path": record["path"],
            "registered_branch": record["branch"],
            "registered_base_sha": record["base_sha"],
            "owner_pid": record.get("owner_pid"),
            "heartbeat_at": record.get("heartbeat_at"),
        }
        attempts = self.store.list_attempts(task["task_id"])
        metadata["latest_attempt"] = attempts[-1] if attempts else None
        session_id = task.get("agent_session_id")
        if session_id:
            session = self.store.get_agent_session(session_id)
            session.pop("command", None)
            metadata["latest_agent_session"] = session
        else:
            metadata["latest_agent_session"] = None
        _write_private(
            target / "metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        commands = {
            "branch.txt": ("branch", "--show-current"),
            "head.txt": ("rev-parse", "HEAD"),
            "status.txt": ("status", "--porcelain=v1", "--untracked-files=all"),
            "worktree.diff": ("diff", "--binary"),
            "staged.diff": ("diff", "--cached", "--binary"),
            "conflicts.txt": ("diff", "--name-only", "--diff-filter=U"),
        }
        if worktree.exists():
            for filename, command in commands.items():
                completed = git(worktree, *command, check=False)
                output = completed.stdout
                if completed.stderr:
                    output += f"\n[stderr]\n{completed.stderr}"
                _write_private(target / filename, output)
            self._copy_untracked(worktree, target)
        else:
            _write_private(target / "status.txt", "worktree path is missing\n")

    @staticmethod
    def _copy_untracked(worktree: Path, target: Path) -> None:
        completed = git(
            worktree, "ls-files", "--others", "--exclude-standard", "-z", check=False
        )
        symlinks: list[dict[str, str]] = []
        for relative in filter(None, completed.stdout.split("\0")):
            source = worktree / relative
            try:
                resolved = source.resolve(strict=True)
            except FileNotFoundError:
                continue
            if source.is_symlink():
                symlinks.append({"path": relative, "target": os.readlink(source)})
                continue
            if worktree.resolve() not in resolved.parents or not resolved.is_file():
                continue
            _write_private(target / "untracked" / relative, resolved.read_bytes())
        if symlinks:
            _write_private(
                target / "untracked-symlinks.json",
                json.dumps(symlinks, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

    def _adopt_complete_archive(
        self,
        task_id: str,
        record: dict[str, Any],
        target: Path,
    ) -> dict[str, Any]:
        manifest = target / "manifest.json"
        if not manifest.is_file():
            raise WorktreeError(
                f"Incomplete forensic archive blocks cleanup: {target}"
            )
        self._verify_manifest_contents(target, manifest)
        return self.store.record_forensic_archive(
            task_id=task_id,
            worktree_id=int(record["worktree_id"]),
            artifact_path=str(target),
            manifest_sha256=_sha256(manifest),
        )

    @staticmethod
    def _verify_existing(existing: dict[str, Any], expected: Path) -> None:
        path = Path(existing["artifact_path"]).resolve()
        if path != expected.resolve():
            raise WorktreeError("Forensic archive path does not match the managed result path")
        manifest = path / "manifest.json"
        if not manifest.is_file() or _sha256(manifest) != existing["manifest_sha256"]:
            raise WorktreeError("Forensic archive manifest is missing or changed")
        FailureForensics._verify_manifest_contents(path, manifest)

    @staticmethod
    def _verify_manifest_contents(root: Path, manifest: Path) -> None:
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            entries = value["files"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WorktreeError(f"Invalid forensic archive manifest: {exc}") from exc
        if not isinstance(entries, list):
            raise WorktreeError("Invalid forensic archive file list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise WorktreeError("Invalid forensic archive file entry")
            artifact = root / entry["path"]
            resolved = artifact.resolve()
            if root.resolve() not in resolved.parents or artifact.is_symlink():
                raise WorktreeError("Forensic archive entry escapes its managed directory")
            if (
                not resolved.is_file()
                or resolved.stat().st_size != entry.get("size")
                or _sha256(resolved) != entry.get("sha256")
            ):
                raise WorktreeError(
                    f"Forensic archive evidence is missing or changed: {entry['path']}"
                )


class TerminalWorktreeReconciler:
    """Preflight, archive, then clean terminal worktrees under RuntimeLock."""

    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimePaths,
        worktrees: WorktreeManager,
        *,
        archiver: FailureForensics | None = None,
    ) -> None:
        self.store = store
        self.worktrees = worktrees
        self.archiver = archiver or FailureForensics(store, runtime, worktrees)

    def reconcile(self, *, execute: bool) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in self.store.list_worktrees():
            try:
                preview = self.worktrees.cleanup_task(
                    record["task_id"], dry_run=True
                )
                if not execute:
                    results.append(
                        {
                            **preview,
                            "action": "would_archive_and_clean",
                        }
                    )
                    continue
                archive = self.archiver.capture(record["task_id"])
                cleaned = self.worktrees.cleanup_task(
                    record["task_id"],
                    dry_run=False,
                    forensic_archive_id=archive["archive_id"],
                )
                results.append(
                    {
                        **cleaned,
                        "forensic_archive_id": archive["archive_id"],
                        "forensic_artifact_path": archive["artifact_path"],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "task_id": record["task_id"],
                        "path": record["path"],
                        "action": "retained",
                        "reason": str(exc),
                    }
                )
        return results
