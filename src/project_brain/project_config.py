"""Canonical project execution profiles and revision hashes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .executables import find_executable
from .models import STABLE_ID_PATTERN
from .security import command_contains_secret, contains_known_secret, redact_text


EXECUTION_FIELDS = (
    "repo_path",
    "remote_url",
    "default_branch",
    "worktree_root",
    "codex_command",
    "verification_commands",
    "allowed_commands",
    "auto_push",
    "auto_pr",
)

LEGACY_CONFIG_REQUIRES_UPDATE = "schema_v5_migration_requires_operator_update"


def _has_path_component(value: str) -> bool:
    return Path(value).is_absolute() or os.sep in value or (
        os.altsep is not None and os.altsep in value
    )


def executable_available(value: str) -> bool:
    """Return whether argv[0] names a regular executable file."""
    expanded = str(Path(value).expanduser()) if _has_path_component(value) else value
    if _has_path_component(expanded):
        path = Path(expanded)
        return path.is_file() and os.access(path, os.X_OK)
    return find_executable(expanded) is not None


def resolve_executable(value: str, label: str) -> str:
    """Resolve argv[0] through PATH once and return a launchd-safe absolute path."""
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{label} must be a non-empty executable")
    expanded = str(Path(value).expanduser()) if _has_path_component(value) else value
    candidate = find_executable(expanded)
    if candidate is None:
        raise ConfigurationError(f"{label} was not found or is not executable: {value}")
    resolved = Path(candidate).expanduser().resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ConfigurationError(f"{label} was not found or is not executable: {value}")
    return str(resolved)


def _command(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ConfigurationError(f"{label} must be a non-empty argv array")
    if command_contains_secret(value):
        raise ConfigurationError(f"{label} contains a credential-like argument")
    return list(value)


def _normalize_execution_profile(
    value: dict[str, Any], *, allow_unresolved_codex: bool
) -> dict[str, Any]:
    required = ("project_id", "repo_path", "remote_url", "default_branch", "worktree_root")
    for field in required:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ConfigurationError(f"project {field} must be a non-empty string")
    project_id = value["project_id"]
    if not STABLE_ID_PATTERN.fullmatch(project_id):
        raise ConfigurationError("project_id must be a stable ID")
    remote_url = value["remote_url"].strip().rstrip("/")
    if "://" not in remote_url and not remote_url.startswith("git@"):
        remote_url = str(Path(remote_url).expanduser().resolve())
    elif remote_url.endswith(".git"):
        remote_url = remote_url[:-4]
    if contains_known_secret(remote_url):
        raise ConfigurationError("remote_url must not contain credentials")
    for flag in ("auto_push", "auto_pr"):
        if flag in value and not isinstance(value[flag], bool):
            raise ConfigurationError(f"{flag} must be boolean")
    codex_command = _command(value.get("codex_command") or [], "codex_command")
    if not allow_unresolved_codex:
        codex_command[0] = resolve_executable(codex_command[0], "Codex executable")
    raw_allowed = value.get("allowed_commands") or {}
    if not isinstance(raw_allowed, dict) or any(
        not isinstance(key, str) or not STABLE_ID_PATTERN.fullmatch(key)
        for key in raw_allowed
    ):
        raise ConfigurationError("allowed_commands must map names to argv arrays")
    allowed = {key: _command(raw_allowed[key], f"allowed_commands.{key}") for key in sorted(raw_allowed)}
    raw_checks = value.get("verification_commands") or []
    if not isinstance(raw_checks, list):
        raise ConfigurationError("verification_commands must be an array")
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_checks, start=1):
        if isinstance(raw, list):
            check_id = f"project-check-{index}"
            check = {"id": check_id, "text": f"Project check {index}", "command": _command(raw, "verification command"), "always_run": True}
        elif isinstance(raw, dict):
            unknown = set(raw).difference({"id", "text", "name", "command", "argv", "always_run"})
            if unknown:
                raise ConfigurationError(f"unsupported verification fields: {', '.join(sorted(unknown))}")
            check_id = raw.get("id") or f"project-check-{index}"
            if not isinstance(check_id, str) or not STABLE_ID_PATTERN.fullmatch(check_id):
                raise ConfigurationError("verification command id must be a stable ID")
            if "always_run" in raw and not isinstance(raw["always_run"], bool):
                raise ConfigurationError("verification always_run must be boolean")
            check = {
                "id": check_id,
                "text": str(raw.get("text") or raw.get("name") or check_id),
                "command": _command(raw.get("command") or raw.get("argv"), "verification command"),
                "always_run": bool(raw.get("always_run", True)),
            }
        else:
            raise ConfigurationError("invalid verification command entry")
        if check_id in seen:
            raise ConfigurationError(f"duplicate verification command id: {check_id}")
        seen.add(check_id)
        checks.append(check)
    return {
        "project_id": project_id,
        "repo_path": str(Path(value["repo_path"]).expanduser().resolve()),
        "remote_url": remote_url,
        "default_branch": value["default_branch"].strip(),
        "worktree_root": str(Path(value["worktree_root"]).expanduser().resolve()),
        "codex_command": codex_command,
        "verification_commands": checks,
        "allowed_commands": allowed,
        "auto_push": bool(value.get("auto_push", True)),
        "auto_pr": bool(value.get("auto_pr", True)),
    }


def normalize_execution_profile(value: dict[str, Any]) -> dict[str, Any]:
    """Return the launchd-safe canonical representation used for persistence."""
    return _normalize_execution_profile(value, allow_unresolved_codex=False)


def normalize_legacy_execution_profile(value: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize an unhealthy v4 profile while preserving unresolved argv[0]."""
    return _normalize_execution_profile(value, allow_unresolved_codex=True)


def canonical_profile_json(profile: dict[str, Any]) -> str:
    normalized = normalize_execution_profile(profile)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_legacy_profile_json(profile: dict[str, Any]) -> str:
    normalized = normalize_legacy_execution_profile(profile)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_sha256(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_profile_json(profile).encode("utf-8")).hexdigest()


def legacy_config_sha256(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_legacy_profile_json(profile).encode("utf-8")).hexdigest()


def short_config_hash(value: str | None) -> str | None:
    return value[:12] if value else None


def project_execution_profile(project: dict[str, Any]) -> dict[str, Any]:
    return normalize_execution_profile({key: project[key] for key in ("project_id", *EXECUTION_FIELDS)})


def verification_catalog(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Expose only the stable, non-sensitive identity of trusted checks."""
    if not isinstance(profile, dict):
        return []
    catalog: list[dict[str, Any]] = []
    for check in profile.get("verification_commands") or []:
        if not isinstance(check, dict) or not check.get("id"):
            continue
        catalog.append(
            {
                "id": str(check["id"]),
                "text": redact_text(
                    str(check.get("text") or check.get("name") or check["id"])
                )[:2000],
                "always_run": bool(check.get("always_run", True)),
            }
        )
    return catalog


def verification_coverage(
    profile: dict[str, Any] | None,
    acceptance_criteria: list[Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Derive redacted criterion coverage from the frozen execution profile."""
    catalog = {item["id"]: item for item in verification_catalog(profile)}
    criteria: list[dict[str, Any]] = []
    referenced: set[str] = set()
    for index, criterion in enumerate(acceptance_criteria or [], start=1):
        if isinstance(criterion, dict):
            criterion_id = str(criterion.get("id") or f"criterion-{index}")
            text = str(criterion.get("text") or criterion.get("criterion") or f"Criterion {index}")[:2000]
            verification_id = criterion.get("verification_id")
        else:
            criterion_id = f"criterion-{index}"
            text = str(criterion)[:2000]
            verification_id = None
        check = catalog.get(str(verification_id)) if verification_id else None
        if check is not None:
            referenced.add(str(verification_id))
        criteria.append(
            {
                "criterion_id": criterion_id,
                "criterion_text": text,
                "verification_id": verification_id,
                "evidence_type": "trusted_project_command" if check else "manual_required",
                "trusted_project_command": check is not None,
                "manual_required": check is None,
                "covered_by_frozen_project_configuration": check is not None,
            }
        )
    supplemental = [
        {
            "criterion_id": f"supplemental:{check_id}",
            "criterion_text": str(check["text"])[:2000],
            "verification_id": check_id,
            "evidence_type": "trusted_project_command",
            "trusted_project_command": True,
            "manual_required": False,
            "covered_by_frozen_project_configuration": True,
            "supplemental": True,
        }
        for check_id, check in catalog.items()
        if check.get("always_run") and check_id not in referenced
    ]
    return {"criteria": criteria, "supplemental": supplemental}
