from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from .context import read_project_context
from .gitops import collect_changes, validate_repo
from .models import Project, resolve_ponytail_mode
from .runtime import RuntimePaths
from .store import Store


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "default_branch": project["default_branch"],
        "check_count": len(project["checks"]),
    }


def public_task(task: dict[str, Any], *, include_result: bool = False) -> dict[str, Any]:
    value = {
        "task_id": task["task_id"],
        "project_id": task["project_id"],
        "goal": task["goal"],
        "ponytail_mode": task["ponytail_mode"],
        "status": task["status"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
    }
    if include_result:
        value.update(
            base_sha=task["base_sha"],
            branch=task["branch"],
            worktree_path=task["worktree_path"],
            worktree_retained=bool(
                task["worktree_path"] and Path(task["worktree_path"]).is_dir()
            ),
            codex_exit_code=task["codex_exit_code"],
            codex_summary=task["codex_summary"],
            changed_files=task["changed_files"],
            diff=task["diff_text"],
            diff_size=task["diff_size"],
            diff_truncated=bool(task["diff_truncated"]),
            checks=task["checks"],
            error=task["error"],
        )
    return value


class Service:
    def __init__(self, runtime: RuntimePaths) -> None:
        self.runtime = runtime.ensure()
        self.store = Store(self.runtime.database)
        self.store.initialize()
        self._worker_processes: dict[str, subprocess.Popen] = {}

    def _reap_finished_process(self, task_id: str) -> None:
        process = self._worker_processes.get(task_id)
        if process is None:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return
        self._worker_processes.pop(task_id, None)

    @staticmethod
    def _process_state(pid: int | None) -> str:
        if not pid:
            return "dead"
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return "dead"
        except (PermissionError, OSError):
            return "unknown"
        return "alive"

    def _worker_state(self, task: dict[str, Any]) -> str:
        process = self._worker_processes.get(task["task_id"])
        if process is not None:
            return "alive" if process.poll() is None else "dead"
        return self._process_state(task.get("worker_pid"))

    @staticmethod
    def _request_key(
        *, project_id: str, goal: str, prompt: str, ponytail_mode: str | None
    ) -> str:
        payload = json.dumps(
            {
                "project_id": project_id,
                "goal": goal.strip(),
                "prompt": prompt.strip(),
                "ponytail_mode": ponytail_mode,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _reconcile_dead_worker(self, task: dict[str, Any]) -> dict[str, Any]:
        if task["status"] in {"completed", "failed"}:
            self._reap_finished_process(task["task_id"])
            return task
        worker_state = self._worker_state(task)
        if task["status"] == "queued" and task.get("worker_pid") and worker_state == "dead":
            return self.store.fail_running_task(
                task["task_id"], error="Worker exited before claiming the task; task was not retried"
            )
        if task["status"] == "running" and worker_state == "dead":
            supervisor_state = self._process_state(task.get("codex_supervisor_pid"))
            if supervisor_state in {"alive", "unknown"}:
                return task
            changed_files: list[str] = []
            diff_text = ""
            if task.get("worktree_path") and task.get("base_sha"):
                worktree = Path(task["worktree_path"])
                if worktree.is_dir():
                    try:
                        changed_files, diff_text = collect_changes(
                            worktree, base_sha=task["base_sha"]
                        )
                    except Exception:
                        pass
            return self.store.finish_task(
                task["task_id"],
                status="failed",
                codex_exit_code=None,
                codex_summary="Worker is no longer alive before final result persistence",
                changed_files=changed_files,
                diff_text=diff_text,
                checks=[],
                error="Worker is no longer alive; task was not retried",
            )
        return task

    def health(self) -> dict[str, Any]:
        tasks = [self._reconcile_dead_worker(t) for t in self.store.list_tasks(limit=100)]
        running = len([t for t in tasks if t["status"] == "running"])
        return {
            "status": "ok",
            "schema_version": 1,
            "projects": len(self.store.list_projects()),
            "running_tasks": running,
        }

    def register_project(
        self,
        *,
        project_id: str,
        name: str,
        repo_path: str,
        default_branch: str,
        codex_command: list[str],
        checks: list[list[str]],
    ) -> dict[str, Any]:
        repo = validate_repo(repo_path, default_branch)
        project = self.store.register_project(
            Project(
                project_id=project_id,
                name=name,
                repo_path=str(repo),
                default_branch=default_branch,
                codex_command=codex_command,
                checks=checks,
            )
        )
        return public_project(project)

    def projects_list(self) -> list[dict[str, Any]]:
        return [public_project(item) for item in self.store.list_projects()]

    def project_context_get(self, project_id: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        return {"project": public_project(project), **read_project_context(project["repo_path"])}

    def task_run(
        self,
        *,
        project_id: str,
        goal: str,
        prompt: str,
        ponytail_mode: str | None = None,
    ) -> dict[str, Any]:
        resolve_ponytail_mode(ponytail_mode)
        task, created = self.store.create_or_get_task(
            project_id=project_id,
            goal=goal,
            prompt=prompt,
            request_key=self._request_key(
                project_id=project_id,
                goal=goal,
                prompt=prompt,
                ponytail_mode=ponytail_mode,
            ),
            ponytail_mode=ponytail_mode,
        )
        if not created:
            return {
                "status": "existing",
                "task": public_task(task, include_result=task["status"] in {"completed", "failed"}),
            }
        log_path = self.runtime.logs / f"{task['task_id']}.log"
        process: subprocess.Popen[str] | None = None
        try:
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "project_brain_simplified.worker",
                        "--runtime-root",
                        str(self.runtime.root),
                        "--task-id",
                        task["task_id"],
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                    env={
                        **os.environ,
                        "PYTHONPATH": os.pathsep.join(
                            item
                            for item in (
                                str(Path(__file__).resolve().parents[1]),
                                os.environ.get("PYTHONPATH", ""),
                            )
                            if item
                        ),
                    },
                )
            self.store.record_worker_pid(task["task_id"], pid=process.pid)
            self._worker_processes[task["task_id"]] = process
        except (OSError, RuntimeError) as exc:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            failed = self.store.fail_running_task(
                task["task_id"], error=f"Worker launch failed; task was not retried: {exc}"
            )
            return {"status": "failed", "task": public_task(failed, include_result=True)}
        return {
            "status": "started",
            "task": public_task(task),
        }

    def tasks_list(self, *, project_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return [
            public_task(self._reconcile_dead_worker(item))
            for item in self.store.list_tasks(project_id=project_id, limit=limit)
        ]

    def tasks_get(self, task_id: str) -> dict[str, Any]:
        return public_task(self._reconcile_dead_worker(self.store.get_task(task_id)), include_result=True)
