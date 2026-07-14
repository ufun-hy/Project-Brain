"""Gmail message to canonical-task adapter with no Git or agent ownership."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict
from typing import Any

from .errors import InvalidTaskError, ProjectBrainError
from .models import CanonicalTask
from .store import TaskStore


def compatibility_task_id(message_id: str) -> str:
    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    return f"gmail-{digest}"


class GmailAdapter:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def parse_message(self, message: dict[str, Any]) -> tuple[CanonicalTask, list[str]]:
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise InvalidTaskError("Gmail message requires message_id")
        body = message.get("body")
        if not isinstance(body, str):
            raise InvalidTaskError("Gmail message body must be text")
        normalized = (
            html.unescape(body).strip()
            .replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )
        try:
            value = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise InvalidTaskError(f"Task body must be JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise InvalidTaskError("Task body must be a JSON object")

        warnings: list[str] = []
        task_id = value.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            task_id = compatibility_task_id(message_id)
            warnings.append(
                "Legacy Gmail task omitted task_id; a reproducible compatibility ID was derived from message_id."
            )
        project_id = self._project_id(value)
        try:
            revision = int(value.get("revision", 1))
        except (TypeError, ValueError) as exc:
            raise InvalidTaskError("revision must be an integer") from exc
        dedupe_key = value.get("dedupe_key") or task_id
        task_type = value.get("task_type") or value.get("type")
        if not isinstance(task_type, str):
            raise InvalidTaskError("type must be codex, write_files, or command")
        goal = (
            value.get("goal")
            or value.get("prompt")
            or value.get("pr_title")
            or value.get("commit_message")
            or f"Apply Gmail task {message_id}"
        )
        acceptance = value.get("acceptance_criteria") or []
        payload_keys = {
            "prompt",
            "files",
            "command",
            "commit_message",
            "pr_title",
            "pr_body",
            "timeout_seconds",
        }
        payload = {key: value[key] for key in payload_keys if key in value}
        canonical = CanonicalTask(
            task_id=task_id,
            project_id=project_id,
            dedupe_key=str(dedupe_key),
            revision=revision,
            source_type="gmail",
            source_message_id=message_id,
            goal=str(goal),
            acceptance_criteria=acceptance,
            task_type=task_type,
            payload=payload,
            expires_at=value.get("expires_at"),
            supersedes=value.get("supersedes"),
        )
        canonical.validate()
        return canonical, warnings

    def import_message(self, message: dict[str, Any]) -> dict[str, Any]:
        canonical, warnings = self.parse_message(message)
        task, created = self.store.insert_task(canonical)
        if created:
            for warning in warnings:
                self.store.record_event(
                    task_id=task["task_id"],
                    event_type="compatibility_warning",
                    payload={"warning": warning, "source_message_id": task["source_message_id"]},
                )
        return {
            "message_id": message["message_id"],
            "task_id": task["task_id"],
            "created": created,
            "warnings": warnings,
            "status": task["status"],
        }

    def import_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for message in messages:
            try:
                results.append(self.import_message(message))
            except ProjectBrainError as exc:
                results.append(
                    {
                        "message_id": message.get("message_id"),
                        "created": False,
                        "status": "rejected",
                        "error": str(exc),
                        "error_category": exc.category,
                    }
                )
        return results

    def preview_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for message in messages:
            try:
                canonical, warnings = self.parse_message(message)
                results.append(
                    {
                        "message_id": message.get("message_id"),
                        "status": "valid",
                        "task": asdict(canonical),
                        "warnings": warnings,
                    }
                )
            except ProjectBrainError as exc:
                results.append(
                    {
                        "message_id": message.get("message_id"),
                        "status": "rejected",
                        "error": str(exc),
                        "error_category": exc.category,
                    }
                )
        return results

    def _project_id(self, value: dict[str, Any]) -> str:
        explicit = value.get("project_id")
        if isinstance(explicit, str) and explicit:
            self.store.get_project(explicit)
            return explicit
        legacy = value.get("project")
        if not isinstance(legacy, str) or not legacy:
            raise InvalidTaskError("project_id or legacy project name is required")
        try:
            return self.store.get_project(legacy)["project_id"]
        except InvalidTaskError:
            return self.store.get_project_by_name(legacy)["project_id"]
