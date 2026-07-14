"""Stable Core domain models and state-machine rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .errors import InvalidTaskError

STABLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidTaskError(f"Invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFICATION_FAILED = "verification_failed"
    RETRY_PENDING = "retry_pending"
    NEEDS_CHANGES = "needs_changes"
    AWAITING_REVIEW = "awaiting_review"
    READY_TO_MERGE = "ready_to_merge"
    MERGING = "merging"
    ACCEPTED = "accepted"
    MERGE_FAILED = "merge_failed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


TERMINAL_STATUSES = {
    TaskStatus.ACCEPTED,
    TaskStatus.FAILED,
    TaskStatus.SUPERSEDED,
    TaskStatus.EXPIRED,
}

CLAIMABLE_STATUSES = {
    TaskStatus.PENDING,
    TaskStatus.RETRY_PENDING,
    TaskStatus.NEEDS_CHANGES,
}

WORKTREE_RETAINED_STATUSES = {
    TaskStatus.RUNNING,
    TaskStatus.RETRY_PENDING,
    TaskStatus.VERIFICATION_FAILED,
    TaskStatus.NEEDS_CHANGES,
    TaskStatus.AWAITING_REVIEW,
    TaskStatus.READY_TO_MERGE,
    TaskStatus.MERGING,
    TaskStatus.MERGE_FAILED,
}

ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.AWAITING_REVIEW,
        TaskStatus.VERIFICATION_FAILED,
        TaskStatus.RETRY_PENDING,
        TaskStatus.FAILED,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
    },
    TaskStatus.VERIFICATION_FAILED: {
        TaskStatus.NEEDS_CHANGES,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
        TaskStatus.FAILED,
    },
    TaskStatus.RETRY_PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
    },
    TaskStatus.NEEDS_CHANGES: {
        TaskStatus.RUNNING,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
        TaskStatus.FAILED,
    },
    TaskStatus.AWAITING_REVIEW: {
        TaskStatus.NEEDS_CHANGES,
        TaskStatus.READY_TO_MERGE,
        TaskStatus.SUPERSEDED,
        TaskStatus.EXPIRED,
    },
    TaskStatus.READY_TO_MERGE: {
        TaskStatus.MERGING,
        TaskStatus.NEEDS_CHANGES,
        TaskStatus.SUPERSEDED,
    },
    TaskStatus.MERGING: {TaskStatus.ACCEPTED, TaskStatus.MERGE_FAILED},
    TaskStatus.MERGE_FAILED: {
        TaskStatus.MERGING,
        TaskStatus.NEEDS_CHANGES,
        TaskStatus.FAILED,
    },
    TaskStatus.ACCEPTED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.SUPERSEDED: set(),
    TaskStatus.EXPIRED: set(),
}


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    repo_path: str
    remote_url: str
    default_branch: str = "main"
    worktree_root: str = ""
    codex_command: list[str] = field(
        default_factory=lambda: ["codex", "exec", "--sandbox", "workspace-write", "-"]
    )
    verification_commands: list[dict[str, Any]] = field(default_factory=list)
    allowed_commands: dict[str, list[str]] = field(default_factory=dict)
    auto_push: bool = True
    auto_pr: bool = True
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def as_record(self) -> dict[str, Any]:
        if not STABLE_ID_PATTERN.fullmatch(self.project_id):
            raise InvalidTaskError(
                "project_id must use 1-128 letters, numbers, dots, underscores, or hyphens"
            )
        return asdict(self)


@dataclass(frozen=True)
class CanonicalTask:
    task_id: str
    project_id: str
    dedupe_key: str
    revision: int
    source_type: str
    goal: str
    task_type: str = "codex"
    source_message_id: str | None = None
    acceptance_criteria: list[Any] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    expires_at: str | None = None
    supersedes: str | None = None

    def validate(self) -> None:
        for label, value in (
            ("task_id", self.task_id),
            ("project_id", self.project_id),
            ("dedupe_key", self.dedupe_key),
            ("source_type", self.source_type),
            ("goal", self.goal),
            ("task_type", self.task_type),
        ):
            if not isinstance(value, str) or not value.strip():
                raise InvalidTaskError(f"{label} must be a non-empty string")
        if self.revision < 1:
            raise InvalidTaskError("revision must be at least 1")
        if self.task_type not in {"codex", "write_files", "command"}:
            raise InvalidTaskError("task_type must be codex, write_files, or command")
        if not isinstance(self.acceptance_criteria, list):
            raise InvalidTaskError("acceptance_criteria must be an array")
        if not isinstance(self.payload, dict):
            raise InvalidTaskError("payload must be an object")
        parse_timestamp(self.expires_at)

    def as_record(self) -> dict[str, Any]:
        self.validate()
        record = asdict(self)
        expiry = parse_timestamp(self.expires_at)
        record["expires_at"] = expiry.isoformat() if expiry else None
        return record
