"""GitHub push and Draft PR adapter."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from .commands import git, run_command
from .errors import ExternalCommandError, TransientTaskError


class GitHubAdapter:
    def publish(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: str | Path,
    ) -> dict[str, Any]:
        branch = task["branch"]
        try:
            git(worktree, "push", "-u", "origin", branch, retryable=True, timeout=600)
        except ExternalCommandError as exc:
            raise TransientTaskError(f"Git push failed: {exc}") from exc
        result: dict[str, Any] = {"pushed": True, "pr_url": task.get("pr_url")}
        if not project.get("auto_pr", True):
            return result
        if task.get("pr_url"):
            return result
        try:
            listed = run_command(
                [
                    "gh", "pr", "list", "--head", branch, "--state", "open",
                    "--json", "url", "--limit", "1",
                ],
                cwd=worktree,
                timeout=120,
                retryable=True,
            )
            existing = json.loads(listed.stdout or "[]")
        except (ExternalCommandError, json.JSONDecodeError) as exc:
            raise TransientTaskError(f"Draft PR lookup failed: {exc}") from exc
        if existing:
            result["pr_url"] = existing[0].get("url")
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
        return result
