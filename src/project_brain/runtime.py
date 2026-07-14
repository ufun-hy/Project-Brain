"""Runtime paths kept outside the source repository."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RUNTIME_ROOT_ENV = "PROJECT_BRAIN_RUNTIME_ROOT"


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
        return self.config_dir / "bridge-config.json"

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
        if (
            not project_id
            or project_id in {".", ".."}
            or Path(project_id).name != project_id
            or "/" in project_id
            or "\\" in project_id
        ):
            raise ValueError(f"Unsafe project_id for runtime path: {project_id}")
        return self.worktrees_dir / project_id

    def ensure(self) -> "RuntimePaths":
        for path in (
            self.root,
            self.config_dir,
            self.logs_dir,
            self.results_dir,
            self.worktrees_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self
