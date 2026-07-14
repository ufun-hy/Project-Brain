"""Repository identity checks and post-verification publication seals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import git
from .errors import TaskHistoryError, WorktreeError


def normalize_remote(value: str) -> str:
    raw = value.strip().rstrip("/")
    if "://" not in raw and not raw.startswith("git@"):
        return str(Path(raw).expanduser().resolve())
    return raw[:-4] if raw.endswith(".git") else raw


def actual_origin(repo: str | Path) -> str:
    completed = git(repo, "remote", "get-url", "origin", check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise WorktreeError(f"Repository has no origin remote: {repo}")
    return completed.stdout.strip()


def assert_registered_origin(repo: str | Path, registered: str) -> str:
    actual = actual_origin(repo)
    if normalize_remote(actual) != normalize_remote(registered):
        raise WorktreeError(
            f"Repository origin differs from registered remote: actual={actual} registered={registered}"
        )
    return actual


@dataclass(frozen=True)
class RepositorySeal:
    branch: str
    head: str
    origin: str
    fetch_config: tuple[str, ...]
    default_ref: str
    default_sha: str

    @classmethod
    def capture(
        cls,
        worktree: str | Path,
        *,
        project: dict[str, object],
        expected_branch: str,
        expected_head: str,
    ) -> "RepositorySeal":
        root = Path(worktree).resolve()
        origin = assert_registered_origin(root, str(project["remote_url"]))
        branch = git(root, "branch", "--show-current").stdout.strip()
        head = git(root, "rev-parse", "HEAD").stdout.strip()
        status = git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
        conflicts = git(root, "diff", "--name-only", "--diff-filter=U").stdout
        if branch != expected_branch or head != expected_head or status or conflicts:
            raise TaskHistoryError("Canonical task repository is not clean and stable before verification")
        fetch_config = tuple(
            git(root, "config", "--get-all", "remote.origin.fetch", check=False).stdout.splitlines()
        )
        default_ref = f"refs/remotes/origin/{project['default_branch']}"
        default_sha = git(root, "rev-parse", default_ref).stdout.strip()
        return cls(branch, head, origin, fetch_config, default_ref, default_sha)

    def verify(self, worktree: str | Path, *, project: dict[str, object]) -> None:
        root = Path(worktree).resolve()
        reasons: list[str] = []
        try:
            current_origin = actual_origin(root)
        except WorktreeError:
            current_origin = ""
            reasons.append("origin removed")
            git(root, "remote", "add", "origin", self.origin, check=False)
        if current_origin and normalize_remote(current_origin) != normalize_remote(self.origin):
            reasons.append("origin changed")
            git(root, "remote", "set-url", "origin", self.origin, check=False)
        current_fetch = tuple(
            git(root, "config", "--get-all", "remote.origin.fetch", check=False).stdout.splitlines()
        )
        if current_fetch != self.fetch_config:
            reasons.append("origin fetch configuration changed")
            git(root, "config", "--unset-all", "remote.origin.fetch", check=False)
            for value in self.fetch_config:
                git(root, "config", "--add", "remote.origin.fetch", value, check=False)
        current_default = git(root, "rev-parse", self.default_ref, check=False).stdout.strip()
        if current_default != self.default_sha:
            reasons.append("default remote ref changed")
            git(root, "update-ref", self.default_ref, self.default_sha, check=False)
        branch = git(root, "branch", "--show-current").stdout.strip()
        head = git(root, "rev-parse", "HEAD").stdout.strip()
        status = git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
        conflicts = git(root, "diff", "--name-only", "--diff-filter=U").stdout
        if branch != self.branch:
            reasons.append("task branch changed")
        if head != self.head:
            reasons.append("task commit changed")
        if status:
            reasons.append("task files changed")
        if conflicts:
            reasons.append("task worktree has conflicts")
        try:
            assert_registered_origin(root, str(project["remote_url"]))
        except WorktreeError:
            reasons.append("registered origin mismatch")
        if reasons:
            raise TaskHistoryError(
                "Verification mutated sealed Git state; publication blocked: "
                + ", ".join(dict.fromkeys(reasons))
            )
