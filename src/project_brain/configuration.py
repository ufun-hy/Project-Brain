"""Explicit project configuration planning, application, and export."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .project_config import (
    EXECUTION_FIELDS,
    LEGACY_CONFIG_REQUIRES_UPDATE,
    config_sha256,
    executable_available,
    normalize_execution_profile,
    normalize_legacy_execution_profile,
)
from .projects import ProjectRegistry
from .runtime import RuntimePaths
from .security import contains_known_secret
from .store import TaskStore


CONFIG_SCHEMA_VERSION = 1
TOP_LEVEL_FIELDS = {"schema_version", "projects"}
PROJECT_FIELDS = {
    "project_id", "name", "repo_path", "remote_url", "default_branch",
    "worktree_root", "codex_command", "codex_path", "verification_commands",
    "allowed_commands", "auto_push", "auto_pr",
}


def safe_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "default_branch": project["default_branch"],
        "auto_push": project["auto_push"],
        "auto_pr": project["auto_pr"],
        "config_revision": project.get("config_revision"),
        "config_sha256": project.get("config_sha256"),
        "config_updated_at": project.get("config_updated_at"),
        "config_source": project.get("config_source"),
    }


class ConfigurationManager:
    def __init__(self, store: TaskStore, runtime: RuntimePaths) -> None:
        self.store = store
        self.runtime = runtime
        self.registry = ProjectRegistry(store, runtime)

    def _read(self, path: str | Path | None) -> tuple[list[dict[str, Any]], bool, Path]:
        source = Path(path).expanduser().resolve() if path else self.runtime.config_file
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Missing config: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Invalid JSON in config: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("Config must be a JSON object")
        if contains_known_secret(value):
            raise ConfigurationError("Config contains a credential-like value")
        legacy = "schema_version" not in value
        allowed_top = TOP_LEVEL_FIELDS | ({"mcp_server"} if legacy else set())
        unknown = set(value).difference(allowed_top)
        if unknown:
            raise ConfigurationError(f"Unsupported top-level config fields: {', '.join(sorted(unknown))}")
        if not legacy and (
            type(value["schema_version"]) is not int
            or value["schema_version"] != CONFIG_SCHEMA_VERSION
        ):
            raise ConfigurationError(
                f"Unsupported config schema_version: {value['schema_version']}"
            )
        projects = value.get("projects")
        if legacy and isinstance(projects, dict):
            projects = [dict(item, name=item.get("name") or name) for name, item in projects.items()]
        if not isinstance(projects, list) or any(not isinstance(item, dict) for item in projects):
            raise ConfigurationError("Config requires a projects array")
        for project in projects:
            unknown_project = set(project).difference(PROJECT_FIELDS)
            if unknown_project:
                raise ConfigurationError(
                    f"Unsupported project config fields: {', '.join(sorted(unknown_project))}"
                )
            if "name" in project and (
                not isinstance(project["name"], str) or not project["name"].strip()
            ):
                raise ConfigurationError("Project name must be a non-empty string")
            for flag in ("auto_push", "auto_pr"):
                if flag in project and not isinstance(project[flag], bool):
                    raise ConfigurationError(f"{flag} must be boolean")
            for check in project.get("verification_commands") or []:
                if (
                    isinstance(check, dict)
                    and "always_run" in check
                    and not isinstance(check["always_run"], bool)
                ):
                    raise ConfigurationError("verification always_run must be boolean")
        return list(projects), legacy, source

    def prepare(self, path: str | Path | None) -> tuple[list[dict[str, Any]], bool, Path]:
        projects, legacy, source = self._read(path)
        prepared = [self.registry.prepare(item) for item in projects]
        identifiers = [item["project_id"] for item in prepared]
        names = [item["name"] for item in prepared]
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationError("Config contains duplicate project_id values")
        if len(names) != len(set(names)):
            raise ConfigurationError("Config contains duplicate project names")
        return prepared, legacy, source

    def validate(self, path: str | Path | None) -> dict[str, Any]:
        projects, legacy, source = self.prepare(path)
        if legacy:
            raise ConfigurationError("Legacy config has no schema_version; use config plan for bootstrap guidance")
        return {
            "status": "valid",
            "schema_version": CONFIG_SCHEMA_VERSION,
            "source": str(source),
            "project_count": len(projects),
            "projects": [item["project_id"] for item in projects],
        }

    def plan(self, path: str | Path | None) -> dict[str, Any]:
        prepared, legacy, source = self.prepare(path)
        current = {item["project_id"]: item for item in self.store.list_projects()}
        current_name_owner = {item["name"]: item["project_id"] for item in current.values()}
        for record in prepared:
            owner = current_name_owner.get(record["name"])
            if owner is not None and owner != record["project_id"]:
                raise ConfigurationError(f"Project name is already registered: {record['name']}")
        nonterminal = {
            item["project_id"]: self.store.nonterminal_task_count(item["project_id"])
            for item in current.values()
        }
        changes: list[dict[str, Any]] = []
        for record in prepared:
            profile = normalize_execution_profile(record)
            digest = config_sha256(profile)
            existing = current.get(record["project_id"])
            if existing is None:
                action, current_revision, next_revision, fields = "add", None, 1, list(EXECUTION_FIELDS)
            else:
                existing_profile = (
                    normalize_legacy_execution_profile(existing)
                    if existing.get("config_source") == LEGACY_CONFIG_REQUIRES_UPDATE
                    else normalize_execution_profile(existing)
                )
                changed = [
                    field for field in EXECUTION_FIELDS
                    if profile[field] != existing_profile[field]
                ]
                if record.get("name") != existing.get("name"):
                    changed.append("name")
                execution_changed = digest != existing["config_sha256"]
                action = "update" if execution_changed else ("rename" if changed else "noop")
                current_revision = existing["config_revision"]
                next_revision = current_revision + (1 if execution_changed else 0)
                fields = changed
            changes.append(
                {
                    "project_id": record["project_id"],
                    "action": action,
                    "current_revision": current_revision,
                    "next_revision": next_revision,
                    "current_sha256": existing.get("config_sha256") if existing else None,
                    "next_sha256": digest,
                    "changed_fields": fields,
                    "nonterminal_task_count": nonterminal.get(record["project_id"], 0),
                    "task_snapshot_effect": "existing tasks keep their snapshot; new tasks bind next revision",
                }
            )
        included = {item["project_id"] for item in prepared}
        registered_only = sorted(set(current).difference(included))
        return {
            "status": "legacy_schema" if legacy else "planned",
            "schema_version": None if legacy else CONFIG_SCHEMA_VERSION,
            "source": str(source),
            "changes": changes,
            "registered_only": registered_only,
        }

    def apply(self, path: str | Path | None, *, execute: bool) -> dict[str, Any]:
        plan = self.plan(path)
        if not execute:
            return plan
        prepared, legacy, source = self.prepare(path)
        existing = self.store.list_projects()
        if legacy and existing:
            raise ConfigurationError("Legacy bootstrap import is allowed only before any project is registered")
        applied = self.store.apply_projects(
            prepared,
            source="bootstrap_import" if legacy else "config_apply",
        )
        return {
            **plan,
            "status": "applied",
            "source": str(source),
            "results": [
                {"action": item["action"], "project": safe_project(item["project"])}
                for item in applied
            ],
        }

    def status(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.store.list_projects() else "unconfigured",
            "schema_version": CONFIG_SCHEMA_VERSION,
            "config_file": str(self.runtime.config_file),
            "config_file_exists": self.runtime.config_file.is_file(),
            "registered_projects": [safe_project(item) for item in self.store.list_projects()],
        }

    def export(self, path: str | Path, *, force: bool) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if target.exists() and not force:
            raise ConfigurationError(f"Refusing to overwrite config export: {target}")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        projects = []
        for project in self.store.list_projects():
            if project.get("config_source") == LEGACY_CONFIG_REQUIRES_UPDATE:
                raise ConfigurationError(
                    f"Project {project['project_id']} requires an operator Codex update before export"
                )
            profile = normalize_execution_profile(project)
            projects.append(
                {
                    "project_id": project["project_id"],
                    "name": project["name"],
                    **{field: profile[field] for field in EXECUTION_FIELDS},
                }
            )
        data = json.dumps(
            {"schema_version": CONFIG_SCHEMA_VERSION, "projects": projects},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if force:
                os.replace(temp_name, target)
            else:
                try:
                    os.link(temp_name, target)
                except FileExistsError as exc:
                    raise ConfigurationError(
                        f"Refusing to overwrite config export: {target}"
                    ) from exc
            os.chmod(target, 0o600)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {"status": "exported", "path": str(target), "project_count": len(projects)}


def project_checks(project: dict[str, Any], runtime: RuntimePaths) -> dict[str, Any]:
    repo = Path(project["repo_path"])
    executable = project["codex_command"][0]
    command_available = executable_available(executable)
    try:
        actual_origin = ProjectRegistry._remote_url(repo)
        origin_matches = ProjectRegistry._normalize_remote(actual_origin) == ProjectRegistry._normalize_remote(project["remote_url"])
    except ConfigurationError:
        origin_matches = False
    remote_head = subprocess.run(
        ["git", "-C", str(repo), "ls-remote", "--symref", "origin", "HEAD"],
        text=True,
        capture_output=True,
    )
    expected_ref = f"ref: refs/heads/{project['default_branch']}\tHEAD"
    default_matches = remote_head.returncode == 0 and expected_ref in remote_head.stdout.splitlines()
    checks = [
        {"name": "repository", "passed": repo.is_dir() and (repo / ".git").exists()},
        {"name": "origin", "passed": origin_matches},
        {"name": "default_branch", "passed": default_matches},
        {"name": "codex", "passed": command_available},
        {"name": "launchd_safe_config", "passed": project.get("config_source") != LEGACY_CONFIG_REQUIRES_UPDATE},
        {"name": "gh", "passed": (not project["auto_pr"]) or executable_available("gh")},
        {"name": "worktree_root", "passed": Path(project["worktree_root"]).resolve() == runtime.project_worktree_root(project["project_id"]).resolve()},
    ]
    for check in project["verification_commands"]:
        argv0 = check["command"][0]
        available = executable_available(argv0)
        checks.append({"name": f"verification:{check['id']}", "passed": available})
    return {
        "project": safe_project(project),
        "status": "healthy" if all(item["passed"] for item in checks) else "unhealthy",
        "checks": checks,
        "verification_executed": False,
    }
