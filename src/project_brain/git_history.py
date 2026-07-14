"""Validate and normalize agent-produced Git history inside a task worktree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import git
from .errors import NoChangesError, TaskHistoryError


@dataclass(frozen=True)
class GitSnapshot:
    expected_branch: str
    base_sha: str
    initial_head: str
    initial_status: str


@dataclass(frozen=True)
class NormalizedHistory:
    commit: str
    head_before: str
    source_commits: list[str]
    changed_files: list[str]


class GitHistoryNormalizer:
    def capture(
        self,
        repo: str | Path,
        *,
        expected_branch: str,
        base_sha: str,
    ) -> GitSnapshot:
        path = Path(repo).resolve()
        branch = self._branch(path)
        if branch != expected_branch:
            raise TaskHistoryError(
                f"Task worktree is on {branch or 'detached HEAD'}, expected {expected_branch}"
            )
        head = git(path, "rev-parse", "HEAD").stdout.strip()
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout
        if status.strip():
            raise TaskHistoryError("Task worktree was not clean before agent execution")
        if not self._is_ancestor(path, base_sha, head):
            raise TaskHistoryError("Initial task HEAD does not descend from the recorded base")
        return GitSnapshot(
            expected_branch=expected_branch,
            base_sha=base_sha,
            initial_head=head,
            initial_status=status,
        )

    def normalize(
        self,
        repo: str | Path,
        snapshot: GitSnapshot,
        *,
        message: str,
    ) -> NormalizedHistory:
        path = Path(repo).resolve()
        branch = self._branch(path)
        if branch != snapshot.expected_branch:
            raise TaskHistoryError(
                f"Agent changed branch to {branch or 'detached HEAD'}; expected {snapshot.expected_branch}"
            )
        self._reject_in_progress_state(path)
        head = git(path, "rev-parse", "HEAD").stdout.strip()
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout
        if not self._is_ancestor(path, snapshot.base_sha, head):
            raise TaskHistoryError("Recorded base is no longer an ancestor of task HEAD")
        if not self._is_ancestor(path, snapshot.initial_head, head):
            raise TaskHistoryError("Agent rewrote or reset the task's initial history")
        if head == snapshot.initial_head and status == snapshot.initial_status:
            raise NoChangesError("Task produced no file or commit changes")
        commits_output = git(
            path, "rev-list", "--reverse", f"{snapshot.initial_head}..{head}"
        ).stdout.strip()
        source_commits = commits_output.splitlines() if commits_output else []
        # Normalize only commits produced in this attempt. On a needs-changes
        # attempt, the previous canonical commit remains an ancestor so a push
        # never requires rewriting reviewed remote history.
        git(path, "reset", "--soft", snapshot.initial_head)
        git(path, "add", "-A")
        if git(path, "diff", "--cached", "--quiet", check=False).returncode == 0:
            raise NoChangesError("Task history has no net file changes")
        git(path, "commit", "-m", message)
        commit = git(path, "rev-parse", "HEAD").stdout.strip()
        changed = git(
            path, "diff-tree", "--no-commit-id", "--name-only", "-r", commit
        ).stdout.splitlines()
        return NormalizedHistory(
            commit=commit,
            head_before=head,
            source_commits=source_commits,
            changed_files=changed,
        )

    @staticmethod
    def _branch(repo: Path) -> str:
        return git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()

    @staticmethod
    def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
        return git(
            repo,
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
        ).returncode == 0

    @staticmethod
    def _reject_in_progress_state(repo: Path) -> None:
        unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        if unmerged:
            raise TaskHistoryError(f"Task worktree has unresolved conflicts: {unmerged}")
        for ref in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD"):
            if git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0:
                raise TaskHistoryError(f"Task worktree has in-progress Git state: {ref}")
