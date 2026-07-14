"""GitHub push and Draft PR adapter."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from .commands import git, run_command
from .errors import ExternalCommandError, TaskHistoryError, TransientTaskError
from .repository import assert_registered_origin


class GitHubAdapter:
    def publish(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: str | Path,
    ) -> dict[str, Any]:
        branch = task["branch"]
        assert_registered_origin(worktree, project["remote_url"])
        try:
            git(worktree, "push", "-u", "origin", branch, retryable=True, timeout=600)
        except ExternalCommandError as exc:
            raise TransientTaskError(f"Git push failed: {exc}") from exc
        remote = git(
            worktree,
            "ls-remote",
            "--heads",
            "origin",
            branch,
            retryable=True,
        ).stdout.strip().split()
        if len(remote) != 2 or remote[0] != task.get("commit"):
            raise TaskHistoryError(
                f"Published remote branch does not match canonical commit: {branch}"
            )
        result: dict[str, Any] = {"pushed": True, "pr_url": task.get("pr_url")}
        if not project.get("auto_pr", True):
            assert_registered_origin(worktree, project["remote_url"])
            return result
        try:
            listed = run_command(
                [
                    "gh", "pr", "list", "--head", branch, "--state", "open",
                    "--json", "url,isDraft", "--limit", "1",
                ],
                cwd=worktree,
                timeout=120,
                retryable=True,
            )
            existing = json.loads(listed.stdout or "[]")
        except (ExternalCommandError, json.JSONDecodeError) as exc:
            raise TransientTaskError(f"Draft PR lookup failed: {exc}") from exc
        if existing:
            if existing[0].get("isDraft") is not True:
                raise TaskHistoryError(f"Open PR for {branch} is not a Draft PR")
            result["pr_url"] = existing[0].get("url")
            assert_registered_origin(worktree, project["remote_url"])
            return result
        payload = task.get("payload") or {}
        title = payload.get("pr_title") or payload.get("commit_message") or task["goal"]
        body = payload.get("pr_body") or (
            "Created by Project Brain Core.\n\n"
            f"Task: `{task['task_id']}`\n"
            f"Source: `{task['source_type']}`\n"
            "Execution succeeded and is awaiting review; this PR is not automatically accepted."
        )
        try:
            completed = run_command(
                [
                    "gh",
                    "pr",
                    "create",
                    "--draft",
                    "--base",
                    project["default_branch"],
                    "--head",
                    branch,
                    "--title",
                    str(title),
                    "--body",
                    str(body),
                ],
                cwd=worktree,
                timeout=300,
                retryable=True,
            )
        except ExternalCommandError as exc:
            raise TransientTaskError(f"Draft PR creation failed: {exc}") from exc
        result["pr_url"] = completed.stdout.strip()
        assert_registered_origin(worktree, project["remote_url"])
        return result
