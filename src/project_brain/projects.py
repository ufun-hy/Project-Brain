"""Project registration and explicit Bridge v2 config migration."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .models import Project, STABLE_ID_PATTERN
from .runtime import RuntimePaths
from .security import command_contains_secret, contains_known_secret
from .store import TaskStore


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def stable_legacy_project_id(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(name)}-{digest}"


class ProjectRegistry:
    def __init__(self, store: TaskStore, runtime: RuntimePaths) -> None:
        self.store = store
        self.runtime = runtime

    def register(self, value: dict[str, Any]) -> dict[str, Any]:
        project_id = value.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ConfigurationError("project_id is required for Core project registration")
        if not STABLE_ID_PATTERN.fullmatch(project_id):
            raise ConfigurationError(
                "project_id must use 1-128 letters, numbers, dots, underscores, or hyphens"
            )
        repo = Path(str(value.get("repo_path", ""))).expanduser().resolve()
        if not (repo / ".git").exists():
            raise ConfigurationError(f"Not a Git repository: {repo}")
        worktree_root = Path(
            str(value.get("worktree_root") or self.runtime.project_worktree_root(project_id))
        ).expanduser().resolve()
        if (
            worktree_root == repo
            or worktree_root in repo.parents
            or repo in worktree_root.parents
        ):
            raise ConfigurationError(
                f"worktree_root must be disjoint from the registered checkout: {worktree_root}"
            )
        remote_url = str(value.get("remote_url") or "")
        if not remote_url:
            remote_url = self._remote_url(repo)
        codex_command = value.get("codex_command") or [
            "codex", "exec", "--sandbox", "workspace-write", "-"
        ]
        if not self._valid_command(codex_command):
            raise ConfigurationError("codex_command must be a non-empty array of strings")
        codex_command = list(codex_command)
        raw_allowed = value.get("allowed_commands") or {}
        if not isinstance(raw_allowed, dict) or any(
            not isinstance(name, str) or not self._valid_command(command)
            for name, command in raw_allowed.items()
        ):
            raise ConfigurationError("allowed_commands must map names to command arrays")
        allowed_commands = {name: list(command) for name, command in raw_allowed.items()}
        raw_verification = value.get("verification_commands") or []
        if not isinstance(raw_verification, list):
            raise ConfigurationError("verification_commands must be an array")
        verification_commands = list(raw_verification)
        commands_to_check = [codex_command, *allowed_commands.values()]
        for check in verification_commands:
            if isinstance(check, list):
                if not self._valid_command(check):
                    raise ConfigurationError("Invalid verification command array")
                commands_to_check.append(check)
            elif isinstance(check, dict):
                command = check.get("command") or check.get("argv")
                if not self._valid_command(command):
                    raise ConfigurationError("Invalid verification command object")
                commands_to_check.append(command)
            else:
                raise ConfigurationError("Invalid verification command entry")
        if any(command_contains_secret(command) for command in commands_to_check):
            raise ConfigurationError(
                "Project commands must obtain credentials from the environment, not literal arguments"
            )
        if contains_known_secret(remote_url):
            raise ConfigurationError("remote_url must not contain embedded credentials")
        project = Project(
            project_id=project_id,
            name=str(value.get("name") or project_id),
            repo_path=str(repo),
            remote_url=remote_url,
            default_branch=str(value.get("default_branch") or "main"),
            worktree_root=str(worktree_root),
            codex_command=codex_command,
            verification_commands=verification_commands,
            allowed_commands=allowed_commands,
            auto_push=bool(value.get("auto_push", True)),
            auto_pr=bool(value.get("auto_pr", True)),
        )
        return self.store.register_project(project)

    def load_config(self, path: str | Path | None = None) -> list[dict[str, Any]]:
        config_path = Path(path).expanduser().resolve() if path else self.runtime.config_file
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Missing config: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Invalid JSON in {config_path}: {exc}") from exc
        projects = data.get("projects")
        if isinstance(projects, dict):
            projects = [dict(value, name=value.get("name") or name) for name, value in projects.items()]
        if not isinstance(projects, list):
            raise ConfigurationError("Config requires a projects array")
        return [self.register(project) for project in projects]

    def import_bridge_v2(self, path: str | Path) -> list[dict[str, Any]]:
        """Import legacy config without editing, moving, or deleting the source file."""
        source = Path(path).expanduser().resolve()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigurationError(f"Missing legacy config: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Invalid JSON in {source}: {exc}") from exc
        projects = data.get("projects")
        if not isinstance(projects, dict):
            raise ConfigurationError("Legacy bridge config requires a projects object")
        imported: list[dict[str, Any]] = []
        for name, old in projects.items():
            if not isinstance(old, dict):
                raise ConfigurationError(f"Invalid legacy project: {name}")
            imported.append(
                self.register(
                    {
                        "project_id": stable_legacy_project_id(name),
                        "name": name,
                        "repo_path": old.get("path"),
                        "remote_url": old.get("remote_url", ""),
                        "default_branch": old.get("base_branch", "main"),
                        "codex_command": old.get("codex_command"),
                        "verification_commands": old.get("verification_commands", []),
                        "allowed_commands": old.get("allowed_commands", {}),
                        "auto_push": old.get("auto_push", True),
                        "auto_pr": old.get("auto_pr", True),
                    }
                )
            )
        return imported

    @staticmethod
    def _remote_url(repo: Path) -> str:
        import subprocess

        completed = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ConfigurationError(f"Repository has no origin remote: {repo}")
        return completed.stdout.strip()

    @staticmethod
    def _valid_command(value: Any) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and bool(item) for item in value)
        )
