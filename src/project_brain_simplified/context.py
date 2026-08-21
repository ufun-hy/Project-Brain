from __future__ import annotations

from pathlib import Path
from typing import Any

MEMORY_FILES = (
    ("problem", ".brain/problem.md"),
    ("current", ".brain/current.md"),
    ("decisions", ".brain/decisions.md"),
)


def read_project_context(repo_path: str | Path, *, per_file_limit: int = 30000) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve()
    brain_dir = repo / ".brain"
    context: dict[str, str] = {}
    missing: list[str] = []
    for key, relative in MEMORY_FILES:
        path = repo / relative
        # The allowlist is intentionally fixed, but a symlink at either level
        # could otherwise turn it into an escape hatch for arbitrary files.
        if brain_dir.is_symlink() or path.is_symlink():
            missing.append(relative)
            continue
        resolved = path.resolve()
        if repo not in resolved.parents or not path.is_file():
            missing.append(relative)
            continue
        text = path.read_text(encoding="utf-8")
        context[key] = text[:per_file_limit]
    return {"context": context, "missing": missing}
