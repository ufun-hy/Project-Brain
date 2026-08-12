"""GitHub push and Draft PR adapter."""

from __future__ import annotations

from pathlib import Path
import json
from urllib.parse import urlparse
from typing import Any

from .commands import git, run_command
from .errors import (
    ExternalCommandError,
    PublicationConflictError,
    TaskHistoryError,
    TransientTaskError,
)
from .repository import assert_registered_origin
from .security import redact_text


def _bounded_pr_title(value: Any) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    title = lines[0] if lines else "Project Brain task"
    for prefix in ("任务名称：", "任务名称:", "Task name:", "Task:"):
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix) :].strip()
            break
    title = redact_text(title).strip() or "Project Brain task"
    return title if len(title) <= 120 else title[:117].rstrip() + "..."


def _default_pr_body(task: dict[str, Any]) -> str:
    context = task.get("publication_context")
    if not isinstance(context, dict):
        context = {}
    changed_files = [
        redact_text(str(item))[:500]
        for item in context.get("changed_files", [])[:100]
        if item
    ]
    evidence = {
        str(item.get("criterion_id")): item
        for item in context.get("verification_evidence", [])[:100]
        if isinstance(item, dict) and item.get("criterion_id")
    }
    criteria: list[str] = []
    for index, criterion in enumerate(task.get("acceptance_criteria", [])[:50], start=1):
        if isinstance(criterion, dict):
            criterion_id = str(criterion.get("id") or f"AC-{index:02d}")
            criterion_text = criterion.get("text") or criterion.get("criterion") or criterion_id
        else:
            criterion_id = f"AC-{index:02d}"
            criterion_text = criterion
        verification = evidence.get(criterion_id, {})
        status = str(verification.get("status") or "not_verified")
        mark = "x" if status == "passed" else " "
        criteria.append(
            f"- [{mark}] `{redact_text(criterion_id)[:128]}` "
            f"{redact_text(str(criterion_text))[:1000]} — `{status}`"
        )
    verification_lines = [
        "- `{}:` {} — {}".format(
            redact_text(str(item.get("verification_id") or item.get("criterion_id") or "check"))[:128],
            redact_text(str(item.get("status") or "unknown"))[:64],
            redact_text(str(item.get("evidence_summary") or "No summary recorded"))[:1000],
        )
        for item in context.get("verification_evidence", [])[:100]
        if isinstance(item, dict)
    ]
    known_gaps = ["Human review and an explicit merge decision are still required."]
    if task.get("source_type") == "mcp":
        known_gaps.append(
            "Real ChatGPT web ingress acceptance is tracked separately and cannot be inferred from local or CI evidence in this PR."
        )
    return "\n".join(
        [
            "## Summary",
            "",
            redact_text(str(task.get("goal") or "Project Brain task"))[:4000],
            "",
            "## Changed files",
            "",
            *(f"- `{item}`" for item in changed_files),
            *(["- No changed-file evidence was supplied."] if not changed_files else []),
            "",
            "## Acceptance criteria",
            "",
            *(criteria or ["- No acceptance criteria were supplied."]),
            "",
            "## Verification",
            "",
            *(verification_lines or ["- No verification evidence was recorded; status is `not_verified`."]),
            "",
            "## Known gaps / review boundary",
            "",
            *(f"- {item}" for item in known_gaps),
            "",
            "## Traceability",
            "",
            f"- Task: `{task['task_id']}`",
            f"- Source: `{task['source_type']}`",
            f"- Canonical published head: `{task.get('canonical_published_head_sha') or task.get('commit') or 'not_verified'}`",
            "- Created by Project Brain Core; this pull request remains Draft and is never automatically merged.",
        ]
    )


def github_repository_identity(remote_url: str) -> str:
    value = remote_url.strip()
    if value.startswith("git@github.com:"):
        path = value.split(":", 1)[1]
    else:
        parsed = urlparse(value)
        if parsed.hostname != "github.com":
            raise TaskHistoryError(
                f"Draft PR identity checks require a github.com remote: {remote_url}"
            )
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    components = [component for component in path.split("/") if component]
    if len(components) != 2:
        raise TaskHistoryError(f"Invalid GitHub repository remote: {remote_url}")
    return "/".join(components)


def _head_repository_identity(value: Any) -> str | None:
    if isinstance(value, dict):
        identity = value.get("nameWithOwner")
        return identity if isinstance(identity, str) else None
    if isinstance(value, str):
        return value
    return None


class GitHubAdapter:
    def remote_head(
        self, *, task: dict[str, Any], project: dict[str, Any], worktree: str | Path
    ) -> str | None:
        """Read the exact remote task branch head without publishing anything."""
        assert_registered_origin(worktree, project["remote_url"])
        return self._remote_task_head(worktree=worktree, branch=task["branch"])

    @staticmethod
    def _remote_task_head(
        *, worktree: str | Path, branch: str
    ) -> str | None:
        # Fetch is deliberately best-effort here: a first publication has no
        # remote task branch yet. ls-remote remains the authoritative exact
        # remote observation and never updates a canonical task field.
        git(worktree, "fetch", "origin", branch, retryable=True, check=False)
        remote = git(
            worktree,
            "ls-remote",
            "--heads",
            "origin",
            branch,
            retryable=True,
        ).stdout.strip().split()
        if not remote:
            return None
        if len(remote) != 2:
            raise TaskHistoryError(f"Remote task branch response is malformed: {branch}")
        return remote[0]

    def publish(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: str | Path,
    ) -> dict[str, Any]:
        branch = task["branch"]
        assert_registered_origin(worktree, project["remote_url"])
        candidate_sha = task.get("local_candidate_sha") or task.get("commit")
        expected = (
            task.get("canonical_published_head_sha")
            or task.get("commit")
            or task.get("base_sha")
        )
        canonical_published_head = task.get("canonical_published_head_sha")
        if not candidate_sha or not expected:
            raise TaskHistoryError("Publication requires a candidate and an expected base head")
        observed = self._remote_task_head(worktree=worktree, branch=branch)
        if observed is None and canonical_published_head:
            raise PublicationConflictError(
                f"Published task branch disappeared before publication: {branch}",
                conflict={
                    "branch": branch,
                    "expected_remote_head_sha": canonical_published_head,
                    "observed_remote_head_sha": "",
                    "publication_base_sha": expected,
                    "candidate_sha": candidate_sha,
                },
            )
        candidate_already_remote = observed == candidate_sha
        if (
            observed is not None
            and observed != expected
            and not candidate_already_remote
        ):
            raise PublicationConflictError(
                f"Remote task branch moved before publication: {branch}",
                conflict={
                    "branch": branch,
                    "expected_remote_head_sha": expected,
                    "observed_remote_head_sha": observed,
                    "publication_base_sha": expected,
                    "candidate_sha": candidate_sha,
                },
            )
        if git(
            worktree,
            "merge-base",
            "--is-ancestor",
            expected,
            candidate_sha,
            check=False,
        ).returncode:
            raise PublicationConflictError(
                f"Publication candidate is not descended from the expected head: {branch}",
                conflict={
                    "branch": branch,
                    "expected_remote_head_sha": expected,
                    "observed_remote_head_sha": observed or "",
                    "publication_base_sha": expected,
                    "candidate_sha": candidate_sha,
                },
            )
        if not candidate_already_remote:
            try:
                git(worktree, "push", "-u", "origin", branch, retryable=True, timeout=600)
            except ExternalCommandError as exc:
                after_failure = self._remote_task_head(worktree=worktree, branch=branch)
                if after_failure is None and canonical_published_head:
                    raise PublicationConflictError(
                        f"Published task branch disappeared during publication: {branch}",
                        conflict={
                            "branch": branch,
                            "expected_remote_head_sha": canonical_published_head,
                            "observed_remote_head_sha": "",
                            "publication_base_sha": expected,
                            "candidate_sha": candidate_sha,
                        },
                    ) from exc
                if after_failure is not None and after_failure not in {expected, candidate_sha}:
                    raise PublicationConflictError(
                        f"Remote task branch moved during publication: {branch}",
                        conflict={
                            "branch": branch,
                            "expected_remote_head_sha": expected,
                            "observed_remote_head_sha": after_failure,
                            "publication_base_sha": expected,
                            "candidate_sha": candidate_sha,
                        },
                    ) from exc
                if after_failure == candidate_sha:
                    candidate_already_remote = True
                else:
                    raise TransientTaskError(f"Git push failed: {exc}") from exc
        remote_head = (
            candidate_sha if candidate_already_remote
            else self._remote_task_head(worktree=worktree, branch=branch)
        )
        if remote_head != candidate_sha:
            raise PublicationConflictError(
                f"Published remote branch does not match candidate: {branch}",
                conflict={
                    "branch": branch,
                    "expected_remote_head_sha": expected,
                    "observed_remote_head_sha": remote_head or "",
                    "publication_base_sha": expected,
                    "candidate_sha": candidate_sha,
                },
            )
        result: dict[str, Any] = {
            "pushed": True,
            "resumed": candidate_already_remote,
            "pr_url": task.get("pr_url"),
        }
        if not project.get("auto_pr", True):
            assert_registered_origin(worktree, project["remote_url"])
            return result
        repository_identity = github_repository_identity(project["remote_url"])
        try:
            listed = run_command(
                [
                    "gh", "pr", "list", "--head", branch, "--state", "open",
                    "--repo", repository_identity,
                    "--json",
                    "url,isDraft,baseRefName,headRefName,headRefOid,headRepository",
                    "--limit", "1",
                ],
                cwd=worktree,
                timeout=120,
                retryable=True,
            )
            existing = json.loads(listed.stdout or "[]")
        except (ExternalCommandError, json.JSONDecodeError) as exc:
            raise TransientTaskError(f"Draft PR lookup failed: {exc}") from exc
        if existing:
            existing_pr = existing[0]
            mismatches: list[str] = []
            if existing_pr.get("baseRefName") != project["default_branch"]:
                mismatches.append("base branch")
            if existing_pr.get("headRefName") != branch:
                mismatches.append("head branch")
            if existing_pr.get("headRefOid") != candidate_sha:
                mismatches.append("head commit")
            head_repository = _head_repository_identity(existing_pr.get("headRepository"))
            if (
                not head_repository
                or head_repository.lower() != repository_identity.lower()
            ):
                mismatches.append("head repository")
            if mismatches:
                raise TaskHistoryError(
                    f"Open PR for {branch} has mismatched " + ", ".join(mismatches)
                )
            if existing_pr.get("isDraft") is not True:
                raise TaskHistoryError(f"Open PR for {branch} is not a Draft PR")
            result["pr_url"] = existing_pr.get("url")
            assert_registered_origin(worktree, project["remote_url"])
            return result
        payload = task.get("payload") or {}
        title = _bounded_pr_title(
            payload.get("pr_title") or payload.get("commit_message") or task["goal"]
        )
        body = payload.get("pr_body") or _default_pr_body(task)
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
