from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Sequence

from .runtime import RuntimePaths


def run(argv: Sequence[str], *, cwd: Path, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv), cwd=cwd, text=True, capture_output=True, timeout=timeout
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(argv)}\n{detail}")
    return completed


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return normalized[:80] or "task"


def validate_repo(repo_path: str | Path, default_branch: str) -> Path:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        raise RuntimeError(f"Repository does not exist: {repo}")
    run(["git", "rev-parse", "--git-dir"], cwd=repo)
    run(["git", "check-ref-format", "--branch", default_branch], cwd=repo)
    run(["git", "rev-parse", "--verify", f"refs/heads/{default_branch}"], cwd=repo)
    return repo


def create_worktree(
    runtime: RuntimePaths,
    *,
    project_id: str,
    task_id: str,
    repo_path: str,
    default_branch: str,
) -> tuple[Path, str, str]:
    repo = validate_repo(repo_path, default_branch)
    base_sha = run(
        ["git", "rev-parse", f"refs/heads/{default_branch}"], cwd=repo
    ).stdout.strip()
    branch = f"brain/{_safe_component(task_id)}"
    root = (runtime.worktrees / _safe_component(project_id)).resolve()
    if repo == root or repo in root.parents:
        raise RuntimeError("Managed worktrees must not be inside the registered repository")
    root.mkdir(parents=True, exist_ok=True)
    path = (root / _safe_component(task_id)).resolve()
    if root not in path.parents:
        raise RuntimeError("Managed worktree path escaped its root")
    if path.exists():
        raise RuntimeError(f"Task worktree already exists: {task_id}")
    branch_check = run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
    )
    if branch_check.returncode == 0:
        raise RuntimeError(f"Task branch already exists: {branch}")
    run(["git", "worktree", "add", "-b", branch, str(path), base_sha], cwd=repo, timeout=180)
    return path, base_sha, branch


def current_head(worktree: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()


def collect_changes(worktree: Path, *, base_sha: str = "HEAD") -> tuple[list[str], str]:
    tracked = run(
        ["git", "diff", "--name-only", base_sha, "--"], cwd=worktree
    ).stdout.splitlines()
    untracked = run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree
    ).stdout.splitlines()
    changed = sorted(set(item for item in tracked + untracked if item))
    diff = run(
        ["git", "diff", base_sha, "--no-ext-diff", "--no-color"], cwd=worktree
    ).stdout
    if untracked:
        pieces = [diff]
        for rel in untracked:
            path = worktree / rel
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                pieces.append(
                    f"\n--- /dev/null\n+++ b/{rel}\n"
                    + "".join(f"+{line}\n" for line in text.splitlines())
                )
        diff = "".join(pieces)
    return changed, diff
