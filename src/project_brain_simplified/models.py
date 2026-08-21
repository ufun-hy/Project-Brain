from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TASK_STATUSES = {"queued", "running", "completed", "failed"}
PONYTAIL_MODES = {"off", "lite", "full", "ultra"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_id(label: str, value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{label} must be 1-128 letters, numbers, dots, underscores, or hyphens")
    return value


def validate_argv(label: str, value: list[str]) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise ValueError(f"{label} must be a non-empty argv array")
    return list(value)


def validate_ponytail_mode(value: str) -> str:
    if not isinstance(value, str) or value not in PONYTAIL_MODES:
        raise ValueError("ponytail_mode must be one of: off, lite, full, ultra")
    return value


def resolve_ponytail_mode(task_mode: str | None = None) -> str:
    value = task_mode if task_mode is not None else os.environ.get(
        "PROJECT_BRAIN_PONYTAIL_MODE", "lite"
    )
    return validate_ponytail_mode(value)


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    codex_command: list[str] = field(
        default_factory=lambda: ["codex", "exec", "--sandbox", "workspace-write", "-"]
    )
    checks: list[list[str]] = field(default_factory=list)

    def validate(self) -> None:
        validate_id("project_id", self.project_id)
        if not self.name.strip():
            raise ValueError("name must be non-empty")
        if not self.repo_path.strip():
            raise ValueError("repo_path must be non-empty")
        if not self.default_branch.strip():
            raise ValueError("default_branch must be non-empty")
        validate_argv("codex_command", self.codex_command)
        for index, check in enumerate(self.checks, 1):
            validate_argv(f"check {index}", check)


@dataclass(frozen=True)
class CheckResult:
    argv: list[str]
    exit_code: int
    status: str
    output: str
    stdout: str = ""
    stderr: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "exit_code": self.exit_code,
            "status": self.status,
            "output": self.output,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
