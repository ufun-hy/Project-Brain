from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    database: Path
    worktrees: Path
    logs: Path

    @classmethod
    def from_value(cls, value: str | Path | None = None) -> "RuntimePaths":
        raw = value or os.environ.get("PROJECT_BRAIN_SIMPLIFIED_RUNTIME_ROOT")
        root = Path(raw).expanduser() if raw else Path.home() / ".project-brain-simplified"
        root = root.resolve()
        return cls(
            root=root,
            database=root / "project-brain.db",
            worktrees=root / "worktrees",
            logs=root / "logs",
        )

    def ensure(self) -> "RuntimePaths":
        for path in (self.root, self.worktrees, self.logs):
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        return self
