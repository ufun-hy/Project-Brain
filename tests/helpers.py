from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from project_brain.models import CanonicalTask, Project
from project_brain.runtime import RuntimePaths
from project_brain.store import TaskStore


def run(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", "-C", str(repo), *args, check=check)


class CoreFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = RuntimePaths.from_value(self.root / "runtime").ensure()
        self.store = TaskStore(self.runtime.database)
        self.store.initialize()

    def close(self) -> None:
        self.temp.cleanup()

    def add_project(self, project_id: str = "project-one", **overrides: Any) -> dict[str, Any]:
        repo = str(overrides.pop("repo_path", self.root / project_id))
        values: dict[str, Any] = {
            "project_id": project_id,
            "name": project_id,
            "repo_path": repo,
            "remote_url": "file:///tmp/remote.git",
            "default_branch": "main",
            "worktree_root": str(self.runtime.project_worktree_root(project_id)),
            "codex_command": [sys.executable, "exec", "-"],
            "verification_commands": [],
            "allowed_commands": {},
            "auto_push": False,
            "auto_pr": False,
        }
        values.update(overrides)
        return self.store.register_project(Project(**values))

    def add_task(self, task_id: str = "task-one", **overrides: Any) -> dict[str, Any]:
        project_id = str(overrides.pop("project_id", "project-one"))
        values: dict[str, Any] = {
            "task_id": task_id,
            "project_id": project_id,
            "dedupe_key": task_id,
            "revision": 1,
            "source_type": "test",
            "goal": "Exercise the Core task model",
            "task_type": "codex",
            "payload": {"prompt": "test"},
        }
        values.update(overrides)
        task, _ = self.store.insert_task(CanonicalTask(**values))
        return task


def create_remote_clone(root: Path, name: str = "repo") -> tuple[Path, Path]:
    seed = root / f"{name}-seed"
    remote = root / f"{name}.git"
    clone = root / name
    seed.mkdir()
    run("git", "init", "-b", "main", cwd=seed)
    git(seed, "config", "user.email", "test@example.com")
    git(seed, "config", "user.name", "Project Brain Test")
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    git(seed, "add", "README.md")
    git(seed, "commit", "-m", "base")
    run("git", "init", "--bare", str(remote))
    # Set the bare remote HEAD before cloning so hosts whose default initial
    # branch is still `master` check out the intended `main` branch.
    run("git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    run("git", "clone", str(remote), str(clone))
    git(clone, "config", "user.email", "test@example.com")
    git(clone, "config", "user.name", "Project Brain Test")
    # Retain a fallback for older Git clone behavior.
    if not git(clone, "branch", "--show-current").stdout.strip():
        git(clone, "checkout", "-B", "main", "origin/main")
    return clone, remote


def executable_script(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def pythonpath_env(source_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(source_root) + (os.pathsep + existing if existing else "")
    return env
