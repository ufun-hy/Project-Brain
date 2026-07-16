"""Bounded and redacted MCP response presenters."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from project_brain import __version__
from project_brain.application import health_report, task_view
from project_brain.runtime import RuntimePaths
from project_brain.security import redact_text
from project_brain.store import TaskStore


MAX_TEXT = 2_000
MAX_SUMMARY = 1_000
MAX_DETAIL_BYTES = 96 * 1024
MAX_ATTEMPTS = 50
MAX_EVIDENCE = 100
MAX_REVIEWS = 20
MAX_FINDINGS = 50

SAFE_EVENT_PAYLOAD_FIELDS = {
    "attempt_number",
    "by_task_id",
    "canonical_head_sha",
    "category",
    "dispatch_status",
    "head_sha",
    "phase",
    "reason",
    "resolution",
    "retryable",
    "review_id",
    "revision",
    "source_attempt_number",
    "source_type",
    "verification_count",
    "verification_set_id",
    "verdict",
}


def bounded_text(value: Any, *, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    rendered = redact_text(str(value))
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 12)] + "...[truncated]"


def task_summary(task: dict[str, Any], projects: dict[str, dict[str, Any]]) -> dict[str, Any]:
    value = task_view(task, projects)
    return {
        "task_id": value["task_id"],
        "project_id": value["project_id"],
        "project": bounded_text(value.get("project"), limit=256),
        "status": value["status"],
        "attempt_phase": value.get("attempt_phase"),
        "attempt_count": value.get("attempt_count"),
        "created_at": value.get("created_at"),
        "updated_at": value.get("updated_at"),
        "elapsed_seconds": value.get("elapsed_seconds"),
        "branch": bounded_text(value.get("branch"), limit=256),
        "commit": bounded_text(value.get("commit"), limit=128),
        "head_sha": bounded_text(value.get("head_sha"), limit=128),
        "pr_url": bounded_text(value.get("pr_url"), limit=1_000),
        "last_error": bounded_text(value.get("last_error")),
        "next_action": bounded_text(value.get("next_action"), limit=500),
    }


def projects_view(store: TaskStore) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for project in store.list_projects():
        repo = Path(project["repo_path"])
        executable = project.get("codex_command") or []
        command = executable[0] if executable else ""
        codex_available = bool(command) and (
            Path(command).expanduser().exists() if "/" in command else shutil.which(command) is not None
        )
        values.append(
            {
                "project_id": project["project_id"],
                "name": bounded_text(project["name"], limit=256),
                "default_branch": bounded_text(project["default_branch"], limit=256),
                "auto_push": project["auto_push"],
                "auto_pr": project["auto_pr"],
                "health": {
                    "repository_available": repo.exists() and (repo / ".git").exists(),
                    "codex_configured": bool(executable),
                    "codex_available": codex_available,
                },
            }
        )
    return values


def health_view(store: TaskStore, runtime: RuntimePaths) -> dict[str, Any]:
    report = health_report(store, runtime)
    checks: list[dict[str, Any]] = []
    for item in report["checks"]:
        name = item["name"]
        if name == "runtime_root":
            detail = "private runtime is writable" if item["status"] == "passed" else "runtime unavailable"
        elif name in {"git", "gh"} or name.startswith("codex:"):
            detail = "available" if item["status"] == "passed" else "not available"
        elif name.startswith("project:"):
            detail = "repository available" if item["status"] == "passed" else "repository unavailable"
        else:
            detail = bounded_text(item.get("detail"), limit=256)
        checks.append({"name": name, "status": item["status"], "detail": detail})
    counts: dict[str, int] = {}
    for task in store.list_tasks(limit=1000):
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    return {
        "core_version": __version__,
        "schema_version": store.schema_version(),
        "status": report["status"],
        "runtime": {
            "configured": runtime.root.is_dir(),
            "lock": next(
                (item["detail"] for item in checks if item["name"] == "runtime_lock"),
                "unknown",
            ),
        },
        "task_counts": dict(sorted(counts.items())),
        "checks": checks,
    }


def tasks_list_view(
    store: TaskStore,
    *,
    project_id: str | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    projects = {item["project_id"]: item for item in store.list_projects()}
    return [
        task_summary(task, projects)
        for task in store.list_tasks(project_id=project_id, status=status, limit=limit)
    ]


def _finding_view(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "severity": finding.get("severity"),
        "file": bounded_text(finding.get("file"), limit=500),
        "evidence": bounded_text(finding.get("evidence"), limit=MAX_SUMMARY),
        "requirement": bounded_text(finding.get("requirement"), limit=MAX_SUMMARY),
    }


def _event_view(event: dict[str, Any]) -> dict[str, Any]:
    raw_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payload = {
        key: bounded_text(value, limit=500) if isinstance(value, str) else value
        for key, value in raw_payload.items()
        if key in SAFE_EVENT_PAYLOAD_FIELDS and isinstance(value, (str, int, float, bool, type(None)))
    }
    return {
        "event_id": event.get("event_id"),
        "event_type": bounded_text(event.get("event_type"), limit=256),
        "from_status": event.get("from_status"),
        "to_status": event.get("to_status"),
        "payload": payload,
        "created_at": event.get("created_at"),
    }


def _fit_detail_budget(value: dict[str, Any]) -> dict[str, Any]:
    value["response_truncated"] = False
    collections: list[list[Any]] = [
        value["events"],
        value["reviews"],
        value["verification"]["evidence"],
        value["attempts"],
        value["active_findings"],
        value["task"]["acceptance_criteria"],
    ]
    truncated = False
    while len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_DETAIL_BYTES:
        target = next((items for items in collections if items), None)
        if target is None:
            break
        target.pop(0)
        truncated = True
    value["response_truncated"] = truncated
    return value


def task_detail_view(
    store: TaskStore,
    task_id: str,
    *,
    recent_event_limit: int,
) -> dict[str, Any]:
    task = store.get_task(task_id)
    projects = {item["project_id"]: item for item in store.list_projects()}
    summary = task_summary(task, projects)
    summary["acceptance_criteria"] = [
        {
            "id": criterion.get("id"),
            "text": bounded_text(criterion.get("text") or criterion.get("criterion"), limit=MAX_SUMMARY),
            "verification_id": criterion.get("verification_id"),
        }
        if isinstance(criterion, dict)
        else {"id": f"criterion-{index}", "text": bounded_text(criterion, limit=MAX_SUMMARY)}
        for index, criterion in enumerate(task.get("acceptance_criteria", [])[:50], start=1)
    ]
    attempts = [
        {
            "attempt_number": item.get("attempt_number"),
            "status": item.get("status"),
            "phase": item.get("phase"),
            "base_sha": bounded_text(item.get("base_sha"), limit=128),
            "head_sha": bounded_text(item.get("head_sha"), limit=128),
            "verification_set_id": item.get("verification_set_id"),
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
            "error_category": bounded_text(item.get("error_category"), limit=128),
            "error_message": bounded_text(item.get("error_message"), limit=MAX_SUMMARY),
        }
        for item in store.list_attempts(task_id)[-MAX_ATTEMPTS:]
    ]
    verification_set = None
    evidence: list[dict[str, Any]] = []
    if task.get("verification_set_id"):
        verification_set = store.get_verification_set(int(task["verification_set_id"]))
        evidence = [
            {
                "verification_id": item.get("verification_id"),
                "criterion_id": item.get("criterion_id"),
                "criterion_text": bounded_text(item.get("criterion_text"), limit=MAX_SUMMARY),
                "status": item.get("status"),
                "evidence_type": item.get("evidence_type"),
                "evidence_summary": bounded_text(item.get("evidence_summary"), limit=MAX_SUMMARY),
                "exit_code": item.get("exit_code"),
                "artifact_available": bool(item.get("artifact_path")),
                "created_at": item.get("created_at"),
            }
            for item in store.list_verifications(
                task_id, verification_set_id=int(task["verification_set_id"])
            )[:MAX_EVIDENCE]
        ]
    reviews = [
        {
            "review_id": review.get("review_id"),
            "head_sha": bounded_text(review.get("head_sha"), limit=128),
            "verdict": review.get("verdict"),
            "created_at": review.get("created_at"),
            "findings": [_finding_view(item) for item in review.get("findings", [])[:MAX_FINDINGS]],
        }
        for review in store.list_reviews(task_id)[-MAX_REVIEWS:]
    ]
    archive = store.get_forensic_archive(task_id)
    value = {
        "task": summary,
        "attempts": attempts,
        "verification": {
            "set": {
                "verification_set_id": verification_set.get("verification_set_id"),
                "canonical_head_sha": verification_set.get("canonical_head_sha"),
                "source_attempt_number": verification_set.get("source_attempt_number"),
                "status": verification_set.get("status"),
                "created_at": verification_set.get("created_at"),
                "completed_at": verification_set.get("completed_at"),
            }
            if verification_set
            else None,
            "evidence": evidence,
        },
        "reviews": reviews,
        "active_findings": [
            _finding_view(item)
            for item in store.active_review_findings(task_id)[:MAX_FINDINGS]
        ],
        "forensic_archive": {
            "archive_id": archive.get("archive_id"),
            "manifest_sha256": archive.get("manifest_sha256"),
            "created_at": archive.get("created_at"),
            "artifact_available": bool(archive.get("artifact_path")),
        }
        if archive
        else None,
        "events": [
            _event_view(event)
            for event in store.list_events(task_id, limit=recent_event_limit)
        ],
    }
    return _fit_detail_budget(value)
