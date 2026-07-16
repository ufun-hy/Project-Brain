"""Repository-aware project registration validation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .models import Project, STABLE_ID_PATTERN
from .project_config import resolve_executable
from .runtime import RuntimePaths
from .security import command_contains_secret, contains_known_secret
from .store import TaskStore


class ProjectRegistry:
    def __init__(self, store: TaskStore, runtime: RuntimePaths) -> None:
        self.store = store
        self.runtime = runtime

    def register(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.store.register_project(self.prepare(value))

    def prepare(self, value: dict[str, Any]) -> dict[str, Any]:
        """Validate and enrich one project without changing runtime state."""
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
        expected_root = self.runtime.project_worktree_root(project_id).resolve()
        if worktree_root != expected_root:
            raise ConfigurationError(
                f"worktree_root must be the managed runtime path: {expected_root}"
            )
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
        actual_remote = self._remote_url(repo)
        if self._normalize_remote(remote_url) != self._normalize_remote(actual_remote):
            raise ConfigurationError(
                f"registered remote_url does not match repository origin: {remote_url}"
            )
        codex_command = value.get("codex_command")
        if not codex_command:
            codex_command = [
                str(value.get("codex_path") or "codex"),
                "exec",
                "--sandbox",
                "workspace-write",
                "-",
            ]
        if not self._valid_command(codex_command):
            raise ConfigurationError("codex_command must be a non-empty array of strings")
        codex_command = list(codex_command)
        codex_command[0] = resolve_executable(codex_command[0], "Codex executable")
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
        verification_commands: list[dict[str, Any]] = []
        verification_ids: set[str] = set()
        commands_to_check = [codex_command, *allowed_commands.values()]
        for index, check in enumerate(raw_verification, start=1):
            if isinstance(check, list):
                if not self._valid_command(check):
                    raise ConfigurationError("Invalid verification command array")
                commands_to_check.append(check)
                check_id = f"project-check-{index}"
                verification_commands.append(
                    {"id": check_id, "text": f"Project check {index}", "command": list(check)}
                )
            elif isinstance(check, dict):
                command = check.get("command") or check.get("argv")
                if not self._valid_command(command):
                    raise ConfigurationError("Invalid verification command object")
                check_id = check.get("id") or f"project-check-{index}"
                if not isinstance(check_id, str) or not STABLE_ID_PATTERN.fullmatch(check_id):
                    raise ConfigurationError("verification command id must be a stable ID")
                if set(check).difference({"id", "text", "name", "command", "argv", "always_run"}):
                    raise ConfigurationError("Unsupported verification command field")
                commands_to_check.append(command)
                verification_commands.append(
                    {
                        "id": check_id,
                        "text": str(check.get("text") or check.get("name") or check_id),
                        "command": list(command),
                        "always_run": bool(check.get("always_run", True)),
                    }
                )
            else:
                raise ConfigurationError("Invalid verification command entry")
            if check_id in verification_ids:
                raise ConfigurationError(f"Duplicate verification command id: {check_id}")
            verification_ids.add(check_id)
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
            default_branch=str(value.get("default_branch") or self._default_branch(repo)),
            worktree_root=str(worktree_root),
            codex_command=codex_command,
            verification_commands=verification_commands,
            allowed_commands=allowed_commands,
            auto_push=bool(value.get("auto_push", True)),
            auto_pr=bool(value.get("auto_pr", True)),
        )
        return project.as_record()

    @staticmethod
    def _remote_url(repo: Path) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ConfigurationError(f"Repository has no origin remote: {repo}")
        return completed.stdout.strip()

    @staticmethod
    def _default_branch(repo: Path) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            text=True,
            capture_output=True,
        )
        branch = completed.stdout.strip()
        if completed.returncode == 0 and branch.startswith("origin/"):
            return branch.removeprefix("origin/")
        completed = subprocess.run(
            ["git", "-C", str(repo), "remote", "show", "origin"],
            text=True,
            capture_output=True,
        )
        for line in completed.stdout.splitlines():
            if "HEAD branch:" in line:
                value = line.split("HEAD branch:", 1)[1].strip()
                if value:
                    return value
        raise ConfigurationError("Unable to detect the origin default branch; pass --default-branch")

    @staticmethod
    def _valid_command(value: Any) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and bool(item) for item in value)
        )

    @staticmethod
    def _normalize_remote(value: str) -> str:
        raw = value.strip().rstrip("/")
        if "://" not in raw and not raw.startswith("git@"):
            return str(Path(raw).expanduser().resolve())
        return raw[:-4] if raw.endswith(".git") else raw
