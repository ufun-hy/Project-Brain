"""Ponytail mode resolution for Codex child processes.

Project Brain does not vendor Ponytail or make it part of Core state. It only
selects the mode used by the official Ponytail Codex plugin.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from .errors import InvalidTaskError

PONYTAIL_MODES = frozenset({"off", "lite", "full", "ultra"})
DEFAULT_PONYTAIL_MODE = "lite"


def resolve_ponytail_mode(
    task: Mapping[str, Any], *, environment: Mapping[str, str] | None = None
) -> str:
    """Resolve task override -> Project Brain host default -> lite."""
    payload = task.get("payload")
    requested = payload.get("ponytail_mode") if isinstance(payload, dict) else None
    env = environment if environment is not None else os.environ
    mode = requested if requested is not None else env.get(
        "PROJECT_BRAIN_PONYTAIL_MODE", DEFAULT_PONYTAIL_MODE
    )
    if not isinstance(mode, str) or mode not in PONYTAIL_MODES:
        allowed = ", ".join(sorted(PONYTAIL_MODES))
        raise InvalidTaskError(f"ponytail_mode must be one of: {allowed}")
    return mode


def codex_environment(task: Mapping[str, Any]) -> dict[str, str]:
    """Return the inherited child environment with Ponytail's default mode key."""
    environment = dict(os.environ)
    environment["PONYTAIL_DEFAULT_MODE"] = resolve_ponytail_mode(
        task, environment=environment
    )
    return environment


def codex_prompt(task: Mapping[str, Any], prompt: str) -> str:
    """Explicitly activate Ponytail before the actual Codex task prompt."""
    mode = resolve_ponytail_mode(task)
    return f"@ponytail {mode}\n\n{prompt}"
