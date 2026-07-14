"""Best-effort prevention of credential persistence in Core state."""

from __future__ import annotations

import json
import re
from typing import Any

KNOWN_SECRET_PATTERNS = [
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)https://[^/@\s:]+:[^/@\s]+@"),
]

ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)"
    r"\s*[:=]\s*([^\s,;]+)"
)

SECRET_FLAGS = {
    "--api-key",
    "--token",
    "--access-token",
    "--password",
    "--client-secret",
}


def redact_text(value: str) -> str:
    redacted = value
    for pattern in KNOWN_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted


def contains_known_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {
                "api_key",
                "access_token",
                "refresh_token",
                "password",
                "client_secret",
            } and item is not None and item != "":
                return True
            if contains_known_secret(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_known_secret(item) for item in value)
    rendered = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if any(pattern.search(rendered) for pattern in KNOWN_SECRET_PATTERNS):
        return True
    return bool(ASSIGNMENT_PATTERN.search(rendered))


def command_contains_secret(command: list[str]) -> bool:
    for index, argument in enumerate(command):
        lowered = argument.lower()
        if lowered in SECRET_FLAGS and index + 1 < len(command):
            return True
        if any(lowered.startswith(flag + "=") for flag in SECRET_FLAGS):
            return True
        if contains_known_secret(argument):
            return True
    return False
