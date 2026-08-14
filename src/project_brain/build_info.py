"""Immutable source identity embedded in packaged Core helpers."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any


def core_build_sha() -> str | None:
    """Return the packaged Git SHA, or None for an editable source checkout."""
    try:
        raw = resources.files("project_brain").joinpath("build-info.json").read_text(
            encoding="utf-8"
        )
        value: Any = json.loads(raw)
    except (FileNotFoundError, OSError, TypeError, json.JSONDecodeError):
        return None
    sha = value.get("build_sha") if isinstance(value, dict) else None
    if (
        not isinstance(sha, str)
        or len(sha) != 40
        or any(character not in "0123456789abcdef" for character in sha)
    ):
        return None
    return sha
