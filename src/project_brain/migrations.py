"""Transactional data migration hooks that cannot be expressed safely in SQL."""

from __future__ import annotations

import json
import sqlite3
import uuid

from .models import utc_now
from .errors import ConfigurationError
from .project_config import (
    LEGACY_CONFIG_REQUIRES_UPDATE,
    canonical_legacy_profile_json,
    canonical_profile_json,
    config_sha256,
    legacy_config_sha256,
    normalize_execution_profile,
    normalize_legacy_execution_profile,
)


def backfill_project_snapshots(connection: sqlite3.Connection) -> None:
    now = utc_now()
    projects: dict[str, tuple[int, str, str]] = {}
    for row in connection.execute("SELECT * FROM projects ORDER BY project_id"):
        profile = {
            "project_id": row["project_id"],
            "repo_path": row["repo_path"],
            "remote_url": row["remote_url"],
            "default_branch": row["default_branch"],
            "worktree_root": row["worktree_root"],
            "codex_command": json.loads(row["codex_command_json"]),
            "verification_commands": json.loads(row["verification_commands_json"]),
            "allowed_commands": json.loads(row["allowed_commands_json"]),
            "auto_push": bool(row["auto_push"]),
            "auto_pr": bool(row["auto_pr"]),
        }
        try:
            profile = normalize_execution_profile(profile)
            serialized = canonical_profile_json(profile)
            digest = config_sha256(profile)
            source = "schema_v5_migration"
        except ConfigurationError:
            profile = normalize_legacy_execution_profile(profile)
            serialized = canonical_legacy_profile_json(profile)
            digest = legacy_config_sha256(profile)
            source = LEGACY_CONFIG_REQUIRES_UPDATE
        connection.execute(
            "UPDATE projects SET repo_path = ?, remote_url = ?, default_branch = ?, "
            "worktree_root = ?, codex_command_json = ?, verification_commands_json = ?, "
            "allowed_commands_json = ?, auto_push = ?, auto_pr = ?, config_revision = 1, "
            "config_sha256 = ?, config_updated_at = ?, "
            "config_source = ? WHERE project_id = ?",
            (
                profile["repo_path"], profile["remote_url"], profile["default_branch"],
                profile["worktree_root"], json.dumps(profile["codex_command"], separators=(",", ":")),
                json.dumps(profile["verification_commands"], separators=(",", ":")),
                json.dumps(profile["allowed_commands"], separators=(",", ":")),
                int(profile["auto_push"]), int(profile["auto_pr"]), digest, now, source,
                row["project_id"],
            ),
        )
        projects[row["project_id"]] = (1, digest, serialized)
    for row in connection.execute("SELECT task_id, project_id FROM tasks ORDER BY task_id"):
        revision, digest, serialized = projects[row["project_id"]]
        connection.execute(
            "UPDATE tasks SET project_config_revision = ?, project_config_sha256 = ?, "
            "execution_profile_json = ? WHERE task_id = ?",
            (revision, digest, serialized, row["task_id"]),
        )


def create_installation_identity(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO installation_identity(singleton, installation_id, created_at) "
        "VALUES (1, ?, ?)",
        (str(uuid.uuid4()), utc_now()),
    )


DATA_MIGRATIONS = {
    5: backfill_project_snapshots,
    7: create_installation_identity,
}
