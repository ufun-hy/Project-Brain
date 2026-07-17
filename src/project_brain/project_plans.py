"""Commit-bound project mutation plans for product confirmation flows."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .errors import StateConflictError


PLAN_TOKEN_VERSION = 1
TOKEN_FIELDS = (
    "project_id",
    "action",
    "current_revision",
    "next_revision",
    "current_sha256",
    "next_sha256",
    "current_name",
    "next_name",
    "changed_fields",
    "nonterminal_task_count",
    "task_snapshot_effect",
)


def project_plan_token(plan: dict[str, Any]) -> str:
    """Return the deterministic token for exactly one displayed mutation plan."""
    payload = {
        "version": PLAN_TOKEN_VERSION,
        **{field: plan.get(field) for field in TOKEN_FIELDS},
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"v{PLAN_TOKEN_VERSION}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def bind_project_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach a recomputable token without mutating the caller's plan."""
    value = dict(plan)
    value["plan_token"] = project_plan_token(value)
    return value


def require_matching_project_plan(plan: dict[str, Any], provided_token: str | None) -> None:
    """Reject missing, malformed, or stale confirmation tokens."""
    if not provided_token:
        raise StateConflictError(
            "Project apply requires --plan-token from the exact plan shown to the operator"
        )
    expected = project_plan_token(plan)
    if not hmac.compare_digest(provided_token, expected):
        raise StateConflictError(
            "Project configuration changed after planning; refresh and review the new plan"
        )
