"""Runtime paths kept outside the source repository."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

RUNTIME_ROOT_ENV = "PROJECT_BRAIN_RUNTIME_ROOT"
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def from_value(cls, value: str | Path | None = None) -> "RuntimePaths":
        raw = value or os.environ.get(RUNTIME_ROOT_ENV) or "~/.project-brain"
        return cls(Path(raw).expanduser().resolve())

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "project-brain.json"

    @property
    def database(self) -> Path:
        return self.root / "project-brain.db"

    @property
    def lock_file(self) -> Path:
        return self.root / "project-brain.lock"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def worktrees_dir(self) -> Path:
        return self.root / "worktrees"

    def project_worktree_root(self, project_id: str) -> Path:
        if not SAFE_COMPONENT.fullmatch(project_id):
            raise ValueError(f"Unsafe project_id for runtime path: {project_id}")
        return self.worktrees_dir / project_id

    def task_result_dir(self, task_id: str, *, create: bool = False) -> Path:
        if not SAFE_COMPONENT.fullmatch(task_id):
            raise ValueError(f"Unsafe task_id for runtime path: {task_id}")
        root = self.results_dir.resolve()
        candidate = root / task_id
        if candidate.is_symlink():
            raise ValueError(f"Task result path cannot be a symlink: {candidate}")
        resolved = candidate.resolve()
        if root not in resolved.parents:
            raise ValueError(f"Task result path escapes runtime: {resolved}")
        if create:
            resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(resolved, 0o700)
        return resolved

    def ensure(self) -> "RuntimePaths":
        for path in (
            self.root,
            self.config_dir,
            self.logs_dir,
            self.results_dir,
            self.worktrees_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
        return self
