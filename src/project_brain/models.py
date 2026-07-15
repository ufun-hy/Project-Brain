"""Stable Core domain models and state-machine rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .errors import InvalidTaskError

STABLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def validate_stable_id(label: str, value: Any) -> str:
    if not isinstance(value, str) or not STABLE_ID_PATTERN.fullmatch(value):
        raise InvalidTaskError(
            f"{label} must use 1-128 letters, numbers, dots, underscores, or hyphens"
        )
    return value


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
    RECOVERY_BLOCKED = "recovery_blocked"
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


class AttemptPhase(str, Enum):
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    PUBLICATION = "publication"
    REVIEW = "review"


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
    TaskStatus.RECOVERY_BLOCKED,
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
        TaskStatus.RECOVERY_BLOCKED,
        TaskStatus.AWAITING_REVIEW,
        TaskStatus.VERIFICATION_FAILED,
        TaskStatus.RETRY_PENDING,
        TaskStatus.FAILED,
        TaskStatus.EXPIRED,
    },
    TaskStatus.RECOVERY_BLOCKED: {
        TaskStatus.RETRY_PENDING,
        TaskStatus.FAILED,
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
        validate_stable_id("project_id", self.project_id)
        if not isinstance(self.codex_command, list) or not self.codex_command or not all(
            isinstance(item, str) and item for item in self.codex_command
        ):
            raise InvalidTaskError("codex_command must be a non-empty array of strings")
        if not isinstance(self.allowed_commands, dict):
            raise InvalidTaskError("allowed_commands must be an object")
        for name, command in self.allowed_commands.items():
            validate_stable_id("allowed command name", name)
            if not isinstance(command, list) or not command or not all(
                isinstance(item, str) and item for item in command
            ):
                raise InvalidTaskError(f"Invalid allowed command: {name}")
        if not isinstance(self.verification_commands, list):
            raise InvalidTaskError("verification_commands must be an array")
        verification_ids: set[str] = set()
        for index, check in enumerate(self.verification_commands, start=1):
            if isinstance(check, list):
                check_id = f"project-check-{index}"
                command = check
            elif isinstance(check, dict):
                check_id = check.get("id") or f"project-check-{index}"
                command = check.get("command") or check.get("argv")
            else:
                raise InvalidTaskError(f"Invalid verification command at index {index}")
            validate_stable_id("verification command id", check_id)
            if check_id in verification_ids:
                raise InvalidTaskError(f"Duplicate verification command id: {check_id}")
            verification_ids.add(check_id)
            if not isinstance(command, list) or not command or not all(
                isinstance(item, str) and item for item in command
            ):
                raise InvalidTaskError(f"Invalid verification command: {check_id}")
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
        for label, value in (("source_type", self.source_type), ("goal", self.goal)):
            if not isinstance(value, str) or not value.strip():
                raise InvalidTaskError(f"{label} must be a non-empty string")
        validate_stable_id("task_id", self.task_id)
        validate_stable_id("project_id", self.project_id)
        validate_stable_id("dedupe_key", self.dedupe_key)
        if self.supersedes is not None:
            validate_stable_id("supersedes", self.supersedes)
        if self.revision < 1:
            raise InvalidTaskError("revision must be at least 1")
        if self.task_type not in {"codex", "write_files", "command"}:
            raise InvalidTaskError("task_type must be codex, write_files, or command")
        if not isinstance(self.acceptance_criteria, list):
            raise InvalidTaskError("acceptance_criteria must be an array")
        seen_criteria: set[str] = set()
        for index, criterion in enumerate(self.acceptance_criteria, start=1):
            if isinstance(criterion, str):
                if not criterion.strip():
                    raise InvalidTaskError(f"acceptance criterion {index} must not be empty")
                seen_criteria.add(f"criterion-{index}")
                continue
            if not isinstance(criterion, dict):
                raise InvalidTaskError(f"acceptance criterion {index} must be a string or object")
            forbidden = {"command", "argv"}.intersection(criterion)
            if forbidden:
                raise InvalidTaskError(
                    "External acceptance criteria cannot contain command or argv"
                )
            allowed = {"id", "text", "criterion", "verification_id"}
            unknown = set(criterion).difference(allowed)
            if unknown:
                raise InvalidTaskError(
                    f"Unsupported acceptance criterion fields: {', '.join(sorted(unknown))}"
                )
            criterion_id = criterion.get("id") or f"criterion-{index}"
            validate_stable_id("criterion id", criterion_id)
            if criterion_id in seen_criteria:
                raise InvalidTaskError(f"Duplicate criterion id: {criterion_id}")
            seen_criteria.add(criterion_id)
            text = criterion.get("text") or criterion.get("criterion")
            if not isinstance(text, str) or not text.strip():
                raise InvalidTaskError(f"acceptance criterion {criterion_id} requires text")
            verification_id = criterion.get("verification_id")
            if verification_id is not None:
                validate_stable_id("verification_id", verification_id)
        if not isinstance(self.payload, dict):
            raise InvalidTaskError("payload must be an object")
        timeout = self.payload.get("timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600
        ):
            raise InvalidTaskError("timeout_seconds must be an integer from 1 to 3600")
        if self.task_type == "command":
            command_name = self.payload.get("command")
            validate_stable_id("command name", command_name)
            if "argv" in self.payload:
                raise InvalidTaskError("command tasks may reference only an allowlisted command name")
        elif self.task_type == "codex":
            prompt = self.payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise InvalidTaskError("codex task requires a non-empty prompt")
        parse_timestamp(self.expires_at)

    def as_record(self) -> dict[str, Any]:
        self.validate()
        record = asdict(self)
        expiry = parse_timestamp(self.expires_at)
        record["expires_at"] = expiry.isoformat() if expiry else None
        return record
