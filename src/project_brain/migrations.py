"""Transactional data migration hooks that cannot be expressed safely in SQL."""

from __future__ import annotations

import hashlib
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


def migrate_local_task_plan_authority(connection: sqlite3.Connection) -> None:
    """Replace replayable Build 8 tokens with hashes and canonical snapshots."""

    # Ensure the one-time plaintext Build 8 value is overwritten when its row
    # is rewritten, without vacuuming, replacing, or otherwise clearing the DB.
    connection.execute("PRAGMA secure_delete = ON")

    def canonical(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    rows = connection.execute(
        "SELECT * FROM local_task_plans ORDER BY created_at, plan_token_sha256"
    ).fetchall()
    for row in rows:
        raw_token = str(row["plan_token_sha256"])
        token_sha256 = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        request = json.loads(row["canonical_request_json"])
        request_json = canonical(request)
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        plan = json.loads(row["plan_json"])
        plan.pop("plan_token", None)
        plan.pop("plan_hash", None)
        plan.pop("token_fingerprint", None)
        plan.setdefault("canonical_goal", request.get("goal", ""))
        plan.setdefault("canonical_goal_length", len(plan["canonical_goal"]))
        plan.setdefault("goal_constraints", {"minimum": 10, "maximum": 8000})
        plan.setdefault("contract_version", "1.1.0")
        plan_sha256 = hashlib.sha256(canonical(plan).encode("utf-8")).hexdigest()
        plan["plan_hash"] = plan_sha256
        plan["token_fingerprint"] = token_sha256[:12]
        connection.execute(
            """
            UPDATE local_task_plans
            SET plan_token_sha256 = ?, canonical_request_sha256 = ?,
                canonical_request_json = ?, plan_json = ?, plan_sha256 = ?,
                token_fingerprint = ?, contract_version = ?
            WHERE plan_token_sha256 = ?
            """,
            (
                token_sha256,
                request_sha256,
                request_json,
                canonical(plan),
                plan_sha256,
                token_sha256[:12],
                "1.1.0",
                raw_token,
            ),
        )


DATA_MIGRATIONS = {
    5: backfill_project_snapshots,
    7: create_installation_identity,
    10: migrate_local_task_plan_authority,
}
