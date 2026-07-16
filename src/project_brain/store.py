"""Versioned SQLite repository for Project Brain Core state."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import (
    ConfigurationError,
    InvalidTaskError,
    MigrationError,
    StateConflictError,
    StateTransitionError,
)
from .models import (
    ALLOWED_TRANSITIONS,
    AttemptPhase,
    CLAIMABLE_STATUSES,
    CanonicalTask,
    Project,
    TERMINAL_STATUSES,
    TaskStatus,
    parse_timestamp,
    utc_now,
)
from .security import contains_known_secret, redact_text
from .migrations import DATA_MIGRATIONS
from .project_config import canonical_profile_json, config_sha256, normalize_execution_profile
from .schema import MIGRATIONS, SCHEMA_VERSION


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class TaskStore:
    def __init__(
        self,
        database: str | Path,
        *,
        migrations: dict[int, str] | None = None,
        data_migrations: dict[int, Any] | None = None,
        schema_version: int | None = None,
    ) -> None:
        self.database = Path(database).expanduser().resolve()
        self.migrations = dict(MIGRATIONS if migrations is None else migrations)
        self.data_migrations = dict(DATA_MIGRATIONS if data_migrations is None else data_migrations)
        self.supported_schema_version = SCHEMA_VERSION if schema_version is None else schema_version

    def connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.database.parent, 0o700)
        connection = sqlite3.connect(self.database, timeout=30)
        os.chmod(self.database, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction(immediate=True) as connection:
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if user_version > self.supported_schema_version:
                raise MigrationError(
                    f"Database schema {user_version} is newer than supported "
                    f"{self.supported_schema_version}"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if applied and max(applied) > self.supported_schema_version:
                raise MigrationError(
                    f"Database migration {max(applied)} is newer than supported "
                    f"{self.supported_schema_version}"
                )
            for version, migration in sorted(self.migrations.items()):
                if version > self.supported_schema_version:
                    continue
                if version in applied:
                    continue
                for statement in self._migration_statements(migration):
                    connection.execute(statement)
                hook = self.data_migrations.get(version)
                if hook is not None:
                    hook(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            connection.execute(f"PRAGMA user_version = {self.supported_schema_version}")

    @staticmethod
    def _migration_statements(script: str) -> list[str]:
        statements: list[str] = []
        pending = ""
        for character in script:
            pending += character
            if character == ";" and sqlite3.complete_statement(pending):
                statement = pending.strip()
                if statement:
                    statements.append(statement)
                pending = ""
        if pending.strip():
            raise MigrationError("Incomplete SQL migration statement")
        return statements

    def schema_version(self) -> int:
        with self.connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])

    def register_project(
        self, project: Project | dict[str, Any], *, source: str = "project_registration"
    ) -> dict[str, Any]:
        return self.apply_projects([project], source=source)[0]["project"]

    def apply_projects(
        self,
        projects: list[Project | dict[str, Any]],
        *,
        source: str,
        expected_plans: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically add/update projects after every record has been normalized."""
        prepared: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        names: set[str] = set()
        for project in projects:
            if isinstance(project, Project):
                record = project.as_record()
            else:
                record = dict(project)
            profile = normalize_execution_profile(record)
            project_id = profile["project_id"]
            if project_id in identifiers:
                raise InvalidTaskError(f"Duplicate project_id: {project_id}")
            identifiers.add(project_id)
            name = str(record.get("name") or project_id)
            if not name.strip() or name in names:
                raise InvalidTaskError(f"Duplicate or empty project name: {name}")
            names.add(name)
            prepared.append(
                {
                    **profile,
                    "name": name,
                    "config_sha256": config_sha256(profile),
                }
            )
        now = utc_now()
        results: list[dict[str, Any]] = []
        with self.transaction(immediate=True) as connection:
            for record in prepared:
                name_owner = connection.execute(
                    "SELECT project_id FROM projects WHERE name = ? AND project_id != ?",
                    (record["name"], record["project_id"]),
                ).fetchone()
                if name_owner is not None:
                    raise InvalidTaskError(f"Project name is already registered: {record['name']}")
                existing = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (record["project_id"],)
                ).fetchone()
                expected = (expected_plans or {}).get(record["project_id"])
                if expected is not None:
                    current_revision = int(existing["config_revision"]) if existing else None
                    current_sha256 = existing["config_sha256"] if existing else None
                    current_name = existing["name"] if existing else None
                    if (
                        expected.get("project_id") != record["project_id"]
                        or expected.get("current_revision") != current_revision
                        or expected.get("current_sha256") != current_sha256
                        or expected.get("current_name") != current_name
                        or expected.get("next_sha256") != record["config_sha256"]
                        or expected.get("next_name") != record["name"]
                    ):
                        raise StateConflictError(
                            "Project state no longer matches the confirmed mutation plan"
                        )
                reactivating = existing is not None and not bool(existing["registered"])
                if existing is None:
                    action = "add"
                    revision = 1
                    created_at = now
                else:
                    action = "noop" if existing["config_sha256"] == record["config_sha256"] else "update"
                    revision = int(existing["config_revision"]) + (action == "update")
                    created_at = existing["created_at"]
                    if action == "noop" and existing["name"] != record["name"]:
                        action = "rename"
                    if reactivating and action in {"noop", "rename"}:
                        action = "reactivate"
                if expected is not None and (
                    expected.get("action") != action
                    or expected.get("next_revision") != revision
                ):
                    raise StateConflictError(
                        "Project mutation no longer matches the confirmed action"
                    )
                if action == "noop":
                    results.append({"action": action, "project": self._project(existing)})
                    continue
                if action == "rename":
                    connection.execute(
                        "UPDATE projects SET name = ?, updated_at = ? WHERE project_id = ?",
                        (record["name"], now, record["project_id"]),
                    )
                    row = connection.execute(
                        "SELECT * FROM projects WHERE project_id = ?", (record["project_id"],)
                    ).fetchone()
                    assert row is not None
                    results.append({"action": action, "project": self._project(row)})
                    connection.execute(
                        "INSERT INTO events(task_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
                        ("project_config_applied", _json({"project_id": record["project_id"], "action": action, "config_revision": revision, "config_sha256": record["config_sha256"]}), now),
                    )
                    continue
                connection.execute(
                    """
                    INSERT INTO projects(
                        project_id, name, repo_path, remote_url, default_branch,
                        worktree_root, codex_command_json, verification_commands_json,
                        allowed_commands_json, auto_push, auto_pr, created_at, updated_at,
                        config_revision, config_sha256, config_updated_at, config_source,
                        accepting_tasks, registered
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        name=excluded.name, repo_path=excluded.repo_path,
                        remote_url=excluded.remote_url, default_branch=excluded.default_branch,
                        worktree_root=excluded.worktree_root,
                        codex_command_json=excluded.codex_command_json,
                        verification_commands_json=excluded.verification_commands_json,
                        allowed_commands_json=excluded.allowed_commands_json,
                        auto_push=excluded.auto_push, auto_pr=excluded.auto_pr,
                        updated_at=excluded.updated_at, config_revision=excluded.config_revision,
                        config_sha256=excluded.config_sha256,
                        config_updated_at=excluded.config_updated_at,
                        config_source=excluded.config_source,
                        accepting_tasks=excluded.accepting_tasks,
                        registered=1
                    """,
                    (
                        record["project_id"], record["name"], record["repo_path"],
                        record["remote_url"], record["default_branch"], record["worktree_root"],
                        _json(record["codex_command"]), _json(record["verification_commands"]),
                        _json(record["allowed_commands"]), int(record["auto_push"]),
                        int(record["auto_pr"]), created_at, now, revision,
                        record["config_sha256"], now, source,
                        int(existing is None or reactivating or bool(existing["accepting_tasks"])),
                        1,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (record["project_id"],)
                ).fetchone()
                assert row is not None
                results.append({"action": action, "project": self._project(row)})
                connection.execute(
                    "INSERT INTO events(task_id,event_type,payload_json,created_at) VALUES(NULL,?,?,?)",
                    (
                        "project_config_applied",
                        _json({"project_id": record["project_id"], "action": action, "config_revision": revision, "config_sha256": record["config_sha256"]}),
                        now,
                    ),
                )
        return results

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["codex_command"] = _loads(value.pop("codex_command_json"), [])
        value["verification_commands"] = _loads(
            value.pop("verification_commands_json"), []
        )
        value["allowed_commands"] = _loads(value.pop("allowed_commands_json"), {})
        value["auto_push"] = bool(value["auto_push"])
        value["auto_pr"] = bool(value["auto_pr"])
        value["accepting_tasks"] = bool(value.get("accepting_tasks", 1))
        value["registered"] = bool(value.get("registered", 1))
        return value

    def get_project(self, project_id: str, *, include_removed: bool = False) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?"
                + ("" if include_removed else " AND registered = 1"),
                (project_id,),
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unregistered project: {project_id}")
        return self._project(row)

    def get_project_by_name(self, name: str, *, include_removed: bool = False) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE name = ?"
                + ("" if include_removed else " AND registered = 1"),
                (name,),
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unregistered project: {name}")
        return self._project(row)

    def list_projects(self, *, include_removed: bool = False) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects"
                + ("" if include_removed else " WHERE registered = 1")
                + " ORDER BY name"
            ).fetchall()
        return [self._project(row) for row in rows]

    def set_project_accepting(self, project_id: str, accepting: bool) -> dict[str, Any]:
        """Pause or resume new task intake without changing execution snapshots."""
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ? AND registered = 1",
                (project_id,),
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unregistered project: {project_id}")
            connection.execute(
                "UPDATE projects SET accepting_tasks = ?, updated_at = ? WHERE project_id = ?",
                (int(accepting), now, project_id),
            )
            self._event(
                connection,
                None,
                "project_intake_changed",
                None,
                None,
                {"project_id": project_id, "accepting_tasks": accepting},
            )
            updated = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            assert updated is not None
            return self._project(updated)

    def remove_project_registration(self, project_id: str) -> dict[str, Any]:
        """Soft-remove a project while preserving task and event history."""
        terminal = tuple(status.value for status in TERMINAL_STATUSES)
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ? AND registered = 1",
                (project_id,),
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unregistered project: {project_id}")
            active = connection.execute(
                f"SELECT COUNT(*) FROM tasks WHERE project_id = ? "
                f"AND status NOT IN ({','.join('?' for _ in terminal)})",
                (project_id, *terminal),
            ).fetchone()
            if int(active[0]) > 0:
                raise InvalidTaskError(
                    f"Project {project_id} has nonterminal tasks and cannot be removed"
                )
            connection.execute(
                "UPDATE projects SET registered = 0, accepting_tasks = 0, updated_at = ? "
                "WHERE project_id = ?",
                (now, project_id),
            )
            self._event(
                connection,
                None,
                "project_registration_removed",
                None,
                None,
                {"project_id": project_id, "runtime_data_preserved": True},
            )
            updated = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            assert updated is not None
            return self._project(updated)

    def nonterminal_task_count(self, project_id: str) -> int:
        terminal = tuple(status.value for status in TERMINAL_STATUSES)
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM tasks WHERE project_id = ? AND status NOT IN ({','.join('?' for _ in terminal)})",
                (project_id, *terminal),
            ).fetchone()
        return int(row[0])

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["acceptance_criteria"] = _loads(
            value.pop("acceptance_criteria_json"), []
        )
        value["payload"] = _loads(value.pop("payload_json"), {})
        if "execution_profile_json" in value:
            value["execution_profile"] = _loads(value.pop("execution_profile_json"), None)
        value["commit"] = value.pop("commit_sha")
        return value

    def task_execution_profile(self, task: str | dict[str, Any]) -> dict[str, Any]:
        value = self.get_task(task) if isinstance(task, str) else task
        raw = value.get("execution_profile")
        revision = value.get("project_config_revision")
        digest = value.get("project_config_sha256")
        if not isinstance(raw, dict) or not isinstance(revision, int) or revision < 1:
            raise InvalidTaskError("Task execution snapshot is missing or invalid")
        try:
            normalized = normalize_execution_profile(raw)
        except ConfigurationError as exc:
            raise InvalidTaskError("Task execution snapshot is malformed") from exc
        if digest != config_sha256(normalized):
            raise InvalidTaskError("Task execution snapshot hash mismatch")
        if normalized["project_id"] != value["project_id"]:
            raise InvalidTaskError("Task execution snapshot project mismatch")
        return normalized

    def insert_task(self, task: CanonicalTask | dict[str, Any]) -> tuple[dict[str, Any], bool]:
        canonical = task if isinstance(task, CanonicalTask) else CanonicalTask(**task)
        record = canonical.as_record()
        if contains_known_secret(record):
            raise InvalidTaskError("Task contains a credential-like value and was not persisted")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (record["task_id"],)
            ).fetchone()
            if existing is not None:
                return self._task(existing), False
            superseded_row: sqlite3.Row | None = None
            supersession_applied = False
            if record.get("supersedes"):
                superseded_row = connection.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (record["supersedes"],)
                ).fetchone()
                if superseded_row is None:
                    raise InvalidTaskError(
                        f"Superseded task does not exist: {record['supersedes']}"
                    )
                if (
                    superseded_row["project_id"] != record["project_id"]
                    or superseded_row["dedupe_key"] != record["dedupe_key"]
                ):
                    raise InvalidTaskError(
                        "supersedes must reference the same project and dedupe_key"
                    )
                if record["revision"] <= superseded_row["revision"]:
                    raise StateTransitionError(
                        "A superseding task revision must be greater than the referenced task"
                    )
                superseded_status = TaskStatus(superseded_row["status"])
                if superseded_status not in TERMINAL_STATUSES:
                    if TaskStatus.SUPERSEDED not in ALLOWED_TRANSITIONS[superseded_status]:
                        raise StateTransitionError(
                            "Task status cannot be superseded while it owns active or "
                            f"protected state: {superseded_status.value}"
                        )
                    supersession_applied = True
            logical = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? AND dedupe_key = ? AND revision = ?",
                (record["project_id"], record["dedupe_key"], record["revision"]),
            ).fetchone()
            if logical is not None:
                return self._task(logical), False
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (record["project_id"],),
            ).fetchone()
            if project_row is None:
                raise InvalidTaskError(f"Unregistered project: {record['project_id']}")
            if not bool(project_row["registered"]):
                raise InvalidTaskError(f"Unregistered project: {record['project_id']}")
            if not bool(project_row["accepting_tasks"]):
                raise InvalidTaskError(
                    f"Project is paused and not accepting new tasks: {record['project_id']}"
                )
            profile = normalize_execution_profile(self._project(project_row))
            profile_json = canonical_profile_json(profile)
            profile_hash = config_sha256(profile)
            if project_row["config_sha256"] != profile_hash or not project_row["config_revision"]:
                raise InvalidTaskError("Active project configuration hash is invalid")
            trusted_ids = {
                check.get("id")
                for check in _loads(project_row["verification_commands_json"], [])
                if isinstance(check, dict) and check.get("id")
            }
            for criterion in record.get("acceptance_criteria", []):
                if not isinstance(criterion, dict) or not criterion.get("verification_id"):
                    continue
                if criterion["verification_id"] not in trusted_ids:
                    raise InvalidTaskError(
                        f"Unknown trusted verification_id for {record['project_id']}: "
                        f"{criterion['verification_id']}"
                    )
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, project_id, dedupe_key, revision, source_type,
                    source_message_id, goal, acceptance_criteria_json, task_type,
                    payload_json, status, attempt_count, created_at, updated_at,
                    expires_at, supersedes, project_config_revision,
                    project_config_sha256, execution_profile_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["task_id"], record["project_id"], record["dedupe_key"],
                    record["revision"], record["source_type"],
                    record.get("source_message_id"), record["goal"],
                    _json(record.get("acceptance_criteria", [])), record["task_type"],
                    _json(record.get("payload", {})), TaskStatus.PENDING.value,
                    now, now, record.get("expires_at"), record.get("supersedes"),
                    int(project_row["config_revision"]), profile_hash, profile_json,
                ),
            )
            self._event(
                connection,
                record["task_id"],
                "task_created",
                None,
                TaskStatus.PENDING.value,
                {
                    "revision": record["revision"],
                    "source_type": record["source_type"],
                    "project_config_revision": int(project_row["config_revision"]),
                    "project_config_sha256": profile_hash,
                    **(
                        {
                            "supersedes": record["supersedes"],
                            "supersession_applied": supersession_applied,
                        }
                        if record.get("supersedes")
                        else {}
                    ),
                },
            )
            if superseded_row is not None and supersession_applied:
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                    (TaskStatus.SUPERSEDED.value, now, superseded_row["task_id"]),
                )
                self._event(
                    connection,
                    superseded_row["task_id"],
                    "task_superseded",
                    superseded_row["status"],
                    TaskStatus.SUPERSEDED.value,
                    {"by_task_id": record["task_id"]},
                )
            created = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (record["task_id"],)
            ).fetchone()
            assert created is not None
            return self._task(created), True

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unknown task: {task_id}")
        return self._task(row)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        values: list[Any] = []
        if status:
            where.append("status = ?")
            values.append(status)
        if project_id:
            where.append("project_id = ?")
            values.append(project_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        values.append(max(1, min(limit, 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks{clause} ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [self._task(row) for row in rows]

    def list_claim_blocking_tasks(self) -> list[dict[str, Any]]:
        statuses = (TaskStatus.RUNNING.value, TaskStatus.RECOVERY_BLOCKED.value)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status IN (?, ?)
                ORDER BY created_at, task_id
                """,
                statuses,
            ).fetchall()
        return [self._task(row) for row in rows]

    def transition(
        self,
        task_id: str,
        to_status: TaskStatus | str,
        *,
        event_type: str = "status_changed",
        payload: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        target = TaskStatus(to_status)
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            current = TaskStatus(row["status"])
            if target not in ALLOWED_TRANSITIONS[current]:
                raise StateTransitionError(
                    f"Invalid task transition: {current.value} -> {target.value}"
                )
            now = utc_now()
            phase = (
                AttemptPhase.IMPLEMENTATION.value
                if target is TaskStatus.NEEDS_CHANGES
                else row["attempt_phase"]
            )
            connection.execute(
                "UPDATE tasks SET status = ?, attempt_phase = ?, updated_at = ?, "
                "last_error = ? WHERE task_id = ?",
                (
                    target.value,
                    phase,
                    now,
                    redact_text(last_error) if last_error else None,
                    task_id,
                ),
            )
            self._event(
                connection,
                task_id,
                event_type,
                current.value,
                target.value,
                payload or {},
            )
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            assert updated is not None
            return self._task(updated)

    def claim_next(self, *, now: str | None = None) -> dict[str, Any] | None:
        claimed_at = now or utc_now()
        parse_timestamp(claimed_at)
        claimable = tuple(status.value for status in CLAIMABLE_STATUSES)
        expirable = claimable + (TaskStatus.RUNNING.value,)
        with self.transaction(immediate=True) as connection:
            expired = connection.execute(
                f"SELECT task_id, status FROM tasks WHERE status IN ({','.join('?' for _ in expirable)}) "
                "AND expires_at IS NOT NULL AND expires_at <= ?",
                (*expirable, claimed_at),
            ).fetchall()
            for row in expired:
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                    (TaskStatus.EXPIRED.value, claimed_at, row["task_id"]),
                )
                self._event(
                    connection,
                    row["task_id"],
                    "task_expired",
                    row["status"],
                    TaskStatus.EXPIRED.value,
                    {},
                )
            row = connection.execute(
                f"SELECT * FROM tasks WHERE status IN ({','.join('?' for _ in claimable)}) "
                "ORDER BY created_at, task_id LIMIT 1",
                claimable,
            ).fetchone()
            if row is None:
                return None
            phase = (
                AttemptPhase.IMPLEMENTATION.value
                if row["status"] in {TaskStatus.PENDING.value, TaskStatus.NEEDS_CHANGES.value}
                else row["attempt_phase"]
            )
            attempt_number = int(row["attempt_count"]) + 1
            connection.execute(
                "UPDATE tasks SET status = ?, attempt_count = ?, attempt_phase = ?, "
                "updated_at = ?, last_error = NULL "
                "WHERE task_id = ? AND status = ?",
                (
                    TaskStatus.RUNNING.value,
                    attempt_number,
                    phase,
                    claimed_at,
                    row["task_id"],
                    row["status"],
                ),
            )
            connection.execute(
                "INSERT INTO task_attempts(task_id, attempt_number, status, phase, base_sha, "
                "head_sha, verification_set_id, started_at) "
                "VALUES (?, ?, 'running', ?, ?, ?, ?, ?)",
                (
                    row["task_id"],
                    attempt_number,
                    phase,
                    row["commit_sha"] or row["base_sha"],
                    row["head_sha"],
                    row["verification_set_id"],
                    claimed_at,
                ),
            )
            self._event(
                connection,
                row["task_id"],
                "task_claimed",
                row["status"],
                TaskStatus.RUNNING.value,
                {"attempt_number": attempt_number},
            )
            claimed = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)
            ).fetchone()
            assert claimed is not None
            return self._task(claimed)

    def finish_attempt(
        self,
        task_id: str,
        *,
        status: str,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        task = self.get_task(task_id)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE task_attempts
                SET status = ?, error_category = ?, error_message = ?, finished_at = ?
                WHERE task_id = ? AND attempt_number = ?
                """,
                (
                    status,
                    error_category,
                    redact_text(error_message) if error_message else None,
                    utc_now(),
                    task_id,
                    task["attempt_count"],
                ),
            )

    def set_attempt_phase(self, task_id: str, phase: AttemptPhase | str) -> dict[str, Any]:
        phase_value = AttemptPhase(phase).value
        task = self.get_task(task_id)
        with self.transaction(immediate=True) as connection:
            now = utc_now()
            connection.execute(
                "UPDATE tasks SET attempt_phase = ?, updated_at = ? WHERE task_id = ?",
                (phase_value, now, task_id),
            )
            connection.execute(
                "UPDATE task_attempts SET phase = ?, base_sha = COALESCE(base_sha, ?), "
                "head_sha = ? WHERE task_id = ? AND attempt_number = ?",
                (
                    phase_value,
                    task.get("commit") or task.get("base_sha"),
                    task.get("head_sha"),
                    task_id,
                    task["attempt_count"],
                ),
            )
        return self.get_task(task_id)

    def set_task_fields(self, task_id: str, **fields: Any) -> dict[str, Any]:
        aliases = {"commit": "commit_sha"}
        allowed = {
            "branch",
            "base_sha",
            "head_sha",
            "worktree_path",
            "agent_session_id",
            "commit_sha",
            "pr_url",
            "last_error",
            "attempt_phase",
        }
        normalized = {aliases.get(key, key): value for key, value in fields.items()}
        if not normalized or any(key not in allowed for key in normalized):
            raise InvalidTaskError("Unsupported task field update")
        normalized["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in normalized)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                (*normalized.values(), task_id),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            return self._task(row)

    def record_worktree(
        self,
        *,
        task_id: str,
        project_id: str,
        path: str,
        branch: str,
        base_sha: str,
        owner_pid: int | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO worktrees(
                    task_id, project_id, path, branch, base_sha, status,
                    owner_pid, heartbeat_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    path = excluded.path,
                    branch = excluded.branch,
                    base_sha = excluded.base_sha,
                    status = 'active',
                    owner_pid = excluded.owner_pid,
                    heartbeat_at = excluded.heartbeat_at,
                    cleaned_at = NULL
                """,
                (task_id, project_id, path, branch, base_sha, owner_pid, now, now),
            )
        return self.get_worktree(task_id)

    def bind_worktree(
        self,
        *,
        task_id: str,
        project_id: str,
        path: str,
        branch: str,
        base_sha: str,
        owner_pid: int | None,
    ) -> dict[str, Any]:
        """Atomically bind Git worktree metadata and task execution fields."""
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO worktrees(
                    task_id, project_id, path, branch, base_sha, status,
                    owner_pid, heartbeat_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    path = excluded.path,
                    branch = excluded.branch,
                    base_sha = excluded.base_sha,
                    status = 'active',
                    owner_pid = excluded.owner_pid,
                    heartbeat_at = excluded.heartbeat_at,
                    cleaned_at = NULL
                """,
                (task_id, project_id, path, branch, base_sha, owner_pid, now, now),
            )
            connection.execute(
                """
                UPDATE tasks
                SET branch = ?, base_sha = ?, head_sha = ?, worktree_path = ?, updated_at = ?
                WHERE task_id = ? AND project_id = ?
                """,
                (branch, base_sha, base_sha, path, now, task_id, project_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskError(f"Unable to bind worktree to task: {task_id}")
            self._event(
                connection,
                task_id,
                "worktree_created",
                None,
                None,
                {"path": path, "branch": branch, "base_sha": base_sha},
            )
            row = connection.execute(
                "SELECT * FROM worktrees WHERE task_id = ?", (task_id,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def get_worktree(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM worktrees WHERE task_id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_worktrees(self, *, include_cleaned: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_cleaned else " WHERE status != 'cleaned'"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM worktrees{clause} ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def heartbeat_worktree(self, task_id: str, *, owner_pid: int | None = None) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET heartbeat_at = ?, owner_pid = COALESCE(?, owner_pid) "
                "WHERE task_id = ? AND status = 'active'",
                (utc_now(), owner_pid, task_id),
            )

    def mark_worktree_cleaned(self, task_id: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET status = 'cleaned', owner_pid = NULL, cleaned_at = ? "
                "WHERE task_id = ?",
                (utc_now(), task_id),
            )

    def record_agent_session(
        self,
        *,
        session_id: str,
        task_id: str,
        adapter: str,
        command: list[str],
    ) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO agent_sessions(
                    session_id, task_id, adapter, command_json, status,
                    started_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, 'starting', ?, ?)
                """,
                (session_id, task_id, adapter, _json(command), utc_now(), utc_now()),
            )
            connection.execute(
                "UPDATE tasks SET agent_session_id = ?, updated_at = ? WHERE task_id = ?",
                (session_id, utc_now(), task_id),
            )

    def start_agent_session(
        self,
        session_id: str,
        *,
        child_pid: int,
        child_pgid: int,
        child_identity: dict[str, Any],
    ) -> None:
        required_identity = {
            "pid",
            "pgid",
            "start_marker",
            "executable",
            "command_digest",
        }
        if (
            not isinstance(child_identity, dict)
            or not required_identity.issubset(child_identity)
            or child_identity.get("pid") != child_pid
            or child_identity.get("pgid") != child_pgid
        ):
            raise InvalidTaskError("Agent session requires matching child process identity")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE agent_sessions
                SET status = 'running', child_pid = ?, child_pgid = ?,
                    child_identity_json = ?, heartbeat_at = ?
                WHERE session_id = ? AND status = 'starting'
                """,
                (child_pid, child_pgid, _json(child_identity), now, session_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskError(f"Agent session is not starting: {session_id}")

    def start_unverified_agent_session(
        self,
        session_id: str,
        *,
        child_pid: int,
        child_pgid: int,
    ) -> None:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE agent_sessions
                SET status = 'running', child_pid = ?, child_pgid = ?, heartbeat_at = ?
                WHERE session_id = ? AND status = 'starting'
                """,
                (child_pid, child_pgid, now, session_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskError(f"Agent session is not starting: {session_id}")

    def heartbeat_agent_session(self, session_id: str, *, task_id: str) -> None:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE agent_sessions SET heartbeat_at = ?
                WHERE session_id = ? AND task_id = ? AND status = 'running'
                """,
                (now, session_id, task_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise InvalidTaskError(f"Agent session is not running: {session_id}")
            connection.execute(
                """
                UPDATE worktrees SET heartbeat_at = ?
                WHERE task_id = ? AND status = 'active'
                """,
                (now, task_id),
            )

    def get_agent_session(self, session_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unknown agent session: {session_id}")
        value = dict(row)
        value["command"] = _loads(value.pop("command_json"), [])
        value["child_identity"] = _loads(value.pop("child_identity_json"), None)
        return value

    def active_agent_session(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT sessions.*
                FROM agent_sessions AS sessions
                JOIN tasks ON tasks.agent_session_id = sessions.session_id
                WHERE tasks.task_id = ? AND sessions.status IN ('starting', 'running')
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["command"] = _loads(value.pop("command_json"), [])
        value["child_identity"] = _loads(value.pop("child_identity_json"), None)
        return value

    def finish_agent_session(
        self,
        session_id: str,
        *,
        status: str,
        exit_code: int | None,
        output_summary: str,
    ) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE agent_sessions SET status = ?, exit_code = ?, output_summary = ?, "
                "heartbeat_at = ?, finished_at = ? WHERE session_id = ?",
                (status, exit_code, output_summary, utc_now(), utc_now(), session_id),
            )

    def create_verification_set(
        self,
        task_id: str,
        *,
        canonical_head_sha: str,
    ) -> dict[str, Any]:
        if not isinstance(canonical_head_sha, str) or not canonical_head_sha:
            raise InvalidTaskError("verification set requires a canonical head")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            if task["status"] != TaskStatus.RUNNING.value:
                raise StateTransitionError(f"Task is not running: {task_id}")
            if task["attempt_phase"] != AttemptPhase.VERIFICATION.value:
                raise StateTransitionError(f"Task is not in verification phase: {task_id}")
            if canonical_head_sha != task["commit_sha"]:
                raise InvalidTaskError(
                    "verification set head must match the task canonical commit"
                )
            cursor = connection.execute(
                """
                INSERT INTO verification_sets(
                    task_id, canonical_head_sha, source_attempt_number, status, created_at
                ) VALUES (?, ?, ?, 'running', ?)
                """,
                (task_id, canonical_head_sha, task["attempt_count"], now),
            )
            verification_set_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE tasks SET verification_set_id = ?, updated_at = ? WHERE task_id = ?",
                (verification_set_id, now, task_id),
            )
            connection.execute(
                """
                UPDATE task_attempts SET verification_set_id = ?
                WHERE task_id = ? AND attempt_number = ? AND status = 'running'
                """,
                (verification_set_id, task_id, task["attempt_count"]),
            )
            self._event(
                connection,
                task_id,
                "verification_set_created",
                task["status"],
                task["status"],
                {
                    "verification_set_id": verification_set_id,
                    "canonical_head_sha": canonical_head_sha,
                    "source_attempt_number": task["attempt_count"],
                },
            )
            row = connection.execute(
                "SELECT * FROM verification_sets WHERE verification_set_id = ?",
                (verification_set_id,),
            ).fetchone()
            assert row is not None
            return dict(row)

    def get_verification_set(self, verification_set_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM verification_sets WHERE verification_set_id = ?",
                (verification_set_id,),
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unknown verification set: {verification_set_id}")
        return dict(row)

    def finalize_verification_set(self, verification_set_id: int, *, status: str) -> None:
        if status not in {"completed", "failed"}:
            raise InvalidTaskError("verification set status must be completed or failed")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE verification_sets SET status = ?, completed_at = ?
                WHERE verification_set_id = ? AND status = 'running'
                """,
                (status, now, verification_set_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise StateTransitionError(
                    f"Verification set is not running: {verification_set_id}"
                )

    def record_verification(
        self,
        task_id: str,
        verification_set_id: int,
        result: dict[str, Any],
    ) -> None:
        with self.transaction(immediate=True) as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            verification_set = connection.execute(
                "SELECT * FROM verification_sets WHERE verification_set_id = ?",
                (verification_set_id,),
            ).fetchone()
            if task is None or verification_set is None:
                raise InvalidTaskError("Unknown task or verification set")
            if (
                verification_set["task_id"] != task_id
                or verification_set["status"] != "running"
                or task["verification_set_id"] != verification_set_id
                or task["commit_sha"] != verification_set["canonical_head_sha"]
                or task["attempt_count"] != verification_set["source_attempt_number"]
            ):
                raise StateTransitionError(
                    "Verification evidence does not match the active canonical verification set"
                )
            connection.execute(
                """
                INSERT INTO verification_results(
                    task_id, criterion_id, criterion_text, status, evidence_type,
                    evidence_summary, command_json, exit_code, artifact_path,
                    attempt_number, verification_set_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    result["criterion_id"],
                    result["criterion_text"],
                    result["status"],
                    result["evidence_type"],
                    result["evidence_summary"],
                    _json(result.get("command")) if result.get("command") else None,
                    result.get("exit_code"),
                    result.get("artifact_path"),
                    verification_set["source_attempt_number"],
                    verification_set_id,
                    result.get("created_at") or utc_now(),
                ),
            )

    def list_verifications(
        self,
        task_id: str,
        *,
        attempt_number: int | None = None,
        verification_set_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if attempt_number is not None and verification_set_id is not None:
            raise InvalidTaskError(
                "Filter verification evidence by attempt or verification set, not both"
            )
        where = "task_id = ?"
        values: list[Any] = [task_id]
        if attempt_number is not None:
            where += " AND attempt_number = ?"
            values.append(attempt_number)
        if verification_set_id is not None:
            where += " AND verification_set_id = ?"
            values.append(verification_set_id)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM verification_results WHERE {where} ORDER BY verification_id",
                values,
            ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["command"] = _loads(value.pop("command_json"), None)
            values.append(value)
        return values

    def publication_evidence(self, task_id: str) -> list[dict[str, Any]]:
        """Return evidence bound to the task's exact canonical head and set."""
        with self.connect() as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            verification_set_id = task["verification_set_id"]
            if verification_set_id is None:
                raise StateTransitionError(
                    f"Task has no canonical verification set: {task_id}"
                )
            verification_set = connection.execute(
                "SELECT * FROM verification_sets WHERE verification_set_id = ?",
                (verification_set_id,),
            ).fetchone()
            if (
                verification_set is None
                or verification_set["task_id"] != task_id
                or verification_set["canonical_head_sha"] != task["commit_sha"]
                or verification_set["status"] != "completed"
            ):
                raise StateTransitionError(
                    "Publication evidence is not a completed set for the canonical head"
                )
        return self.list_verifications(
            task_id, verification_set_id=int(verification_set_id)
        )

    def record_forensic_archive(
        self,
        *,
        task_id: str,
        worktree_id: int,
        artifact_path: str,
        manifest_sha256: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO forensic_archives(
                    task_id, worktree_id, artifact_path, manifest_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, worktree_id, artifact_path, manifest_sha256, now),
            )
            archive_id = int(cursor.lastrowid)
            self._event(
                connection,
                task_id,
                "forensic_archive_created",
                None,
                None,
                {
                    "archive_id": archive_id,
                    "worktree_id": worktree_id,
                    "artifact_path": artifact_path,
                    "manifest_sha256": manifest_sha256,
                },
            )
            row = connection.execute(
                "SELECT * FROM forensic_archives WHERE archive_id = ?", (archive_id,)
            ).fetchone()
            assert row is not None
            return dict(row)

    def get_forensic_archive(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM forensic_archives
                WHERE task_id = ? ORDER BY archive_id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_forensic_archive_by_id(self, archive_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM forensic_archives WHERE archive_id = ?", (archive_id,)
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unknown forensic archive: {archive_id}")
        return dict(row)

    def apply_review_verdict(
        self,
        task_id: str,
        *,
        verdict: str,
        findings: list[dict[str, Any]],
        head_sha: str,
    ) -> dict[str, Any]:
        if verdict not in {"approved", "needs_changes"}:
            raise InvalidTaskError("review verdict must be approved or needs_changes")
        if not isinstance(head_sha, str) or not head_sha:
            raise InvalidTaskError("review head_sha is required")
        if not isinstance(findings, list):
            raise InvalidTaskError("review findings must be an array")
        normalized: list[dict[str, Any]] = []
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                raise InvalidTaskError(f"review finding {index} must be an object")
            unknown = set(finding).difference({"severity", "file", "evidence", "requirement"})
            if unknown:
                raise InvalidTaskError(
                    f"Unsupported review finding fields: {', '.join(sorted(unknown))}"
                )
            severity = finding.get("severity")
            evidence = finding.get("evidence")
            requirement = finding.get("requirement")
            file_value = finding.get("file")
            if severity not in {"blocker", "critical", "major", "minor", "nit"}:
                raise InvalidTaskError(f"Invalid review finding severity: {severity}")
            if not isinstance(evidence, str) or not evidence.strip():
                raise InvalidTaskError("review finding evidence must be non-empty")
            if not isinstance(requirement, str) or not requirement.strip():
                raise InvalidTaskError("review finding requirement must be non-empty")
            if file_value is not None and (
                not isinstance(file_value, str) or not file_value.strip()
            ):
                raise InvalidTaskError("review finding file must be a non-empty string")
            normalized.append(
                {
                    "severity": severity,
                    "file": redact_text(file_value) if file_value else None,
                    "evidence": redact_text(evidence),
                    "requirement": redact_text(requirement),
                }
            )
        if verdict == "needs_changes" and not normalized:
            raise InvalidTaskError("needs_changes review requires at least one finding")
        if verdict == "approved" and any(
            finding["severity"] in {"blocker", "critical"} for finding in normalized
        ):
            raise InvalidTaskError(
                "approved review cannot contain blocker or critical findings"
            )
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            current = TaskStatus(task["status"])
            if current not in {
                TaskStatus.AWAITING_REVIEW,
                TaskStatus.VERIFICATION_FAILED,
            }:
                raise StateTransitionError(
                    f"Task cannot receive a review verdict in state: {current.value}"
                )
            if current is TaskStatus.VERIFICATION_FAILED and verdict != "needs_changes":
                raise StateTransitionError(
                    "verification_failed task requires a needs_changes verdict"
                )
            canonical_head = task["commit_sha"] or task["head_sha"]
            if not canonical_head or head_sha != canonical_head:
                raise InvalidTaskError(
                    "review head_sha must exactly match the task canonical commit"
                )
            target = (
                TaskStatus.NEEDS_CHANGES
                if verdict == "needs_changes"
                else TaskStatus.READY_TO_MERGE
            )
            if target not in ALLOWED_TRANSITIONS[current]:
                raise StateTransitionError(
                    f"Invalid review transition: {current.value} -> {target.value}"
                )
            cursor = connection.execute(
                "INSERT INTO reviews(task_id, head_sha, verdict, created_at) VALUES (?, ?, ?, ?)",
                (task_id, head_sha, verdict, now),
            )
            review_id = int(cursor.lastrowid)
            for finding in normalized:
                connection.execute(
                    """
                    INSERT INTO review_findings(
                        review_id, task_id, head_sha, severity, file, evidence,
                        requirement, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        task_id,
                        head_sha,
                        finding["severity"],
                        finding["file"],
                        finding["evidence"],
                        finding["requirement"],
                        now,
                    ),
                )
            phase = (
                AttemptPhase.IMPLEMENTATION.value
                if target is TaskStatus.NEEDS_CHANGES
                else task["attempt_phase"]
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, attempt_phase = ?, updated_at = ?, last_error = NULL
                WHERE task_id = ?
                """,
                (target.value, phase, now, task_id),
            )
            self._event(
                connection,
                task_id,
                "review_verdict_applied",
                current.value,
                target.value,
                {"review_id": review_id, "head_sha": head_sha, "verdict": verdict},
            )
        return {
            "review": self.get_review(review_id),
            "task": self.get_task(task_id),
        }

    def get_review(self, review_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
            findings = connection.execute(
                "SELECT * FROM review_findings WHERE review_id = ? ORDER BY finding_id",
                (review_id,),
            ).fetchall()
        if row is None:
            raise InvalidTaskError(f"Unknown review: {review_id}")
        value = dict(row)
        value["findings"] = [dict(item) for item in findings]
        return value

    def list_reviews(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT review_id FROM reviews WHERE task_id = ? ORDER BY review_id",
                (task_id,),
            ).fetchall()
        return [self.get_review(int(row["review_id"])) for row in rows]

    def active_review_findings(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        head_sha = task.get("commit") or task.get("head_sha")
        if not head_sha:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT review_findings.*
                FROM review_findings
                JOIN reviews USING(review_id)
                WHERE review_findings.task_id = ?
                  AND review_findings.head_sha = ?
                  AND reviews.verdict = 'needs_changes'
                ORDER BY finding_id
                """,
                (task_id, head_sha),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_running_task(
        self,
        task_id: str,
        *,
        target: TaskStatus | str,
        reason: str,
    ) -> dict[str, Any]:
        target_status = TaskStatus(target)
        if target_status not in {
            TaskStatus.RETRY_PENDING,
            TaskStatus.AWAITING_REVIEW,
            TaskStatus.FAILED,
        }:
            raise InvalidTaskError(f"Unsupported recovery target: {target_status.value}")
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            if row["status"] != TaskStatus.RUNNING.value:
                raise StateTransitionError(f"Task is not running: {task_id}")
            now = utc_now()
            message = redact_text(reason)
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, last_error = ? WHERE task_id = ?",
                (target_status.value, now, message, task_id),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET status = 'interrupted', error_category = 'recovery',
                    error_message = ?, finished_at = ?
                WHERE task_id = ? AND attempt_number = ? AND status = 'running'
                """,
                (message, now, task_id, row["attempt_count"]),
            )
            connection.execute(
                """
                UPDATE agent_sessions
                SET status = 'interrupted', output_summary = ?, finished_at = ?
                WHERE task_id = ? AND status IN ('starting', 'running')
                """,
                (message, now, task_id),
            )
            self._event(
                connection,
                task_id,
                "task_recovered",
                TaskStatus.RUNNING.value,
                target_status.value,
                {"reason": message, "phase": row["attempt_phase"]},
            )
        return self.get_task(task_id)

    def block_running_task(self, task_id: str, *, reason: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            if row["status"] != TaskStatus.RUNNING.value:
                raise StateTransitionError(f"Task is not running: {task_id}")
            now = utc_now()
            message = redact_text(reason)
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, last_error = ? WHERE task_id = ?",
                (TaskStatus.RECOVERY_BLOCKED.value, now, message, task_id),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET status = ?, error_category = 'recovery', error_message = ?, finished_at = ?
                WHERE task_id = ? AND attempt_number = ? AND status = 'running'
                """,
                (
                    TaskStatus.RECOVERY_BLOCKED.value,
                    message,
                    now,
                    task_id,
                    row["attempt_count"],
                ),
            )
            connection.execute(
                """
                UPDATE agent_sessions
                SET status = ?, output_summary = ?, heartbeat_at = ?, finished_at = ?
                WHERE task_id = ? AND status IN ('starting', 'running')
                """,
                (
                    TaskStatus.RECOVERY_BLOCKED.value,
                    message,
                    now,
                    now,
                    task_id,
                ),
            )
            self._event(
                connection,
                task_id,
                "task_recovery_blocked",
                TaskStatus.RUNNING.value,
                TaskStatus.RECOVERY_BLOCKED.value,
                {"reason": message, "phase": row["attempt_phase"]},
            )
        return self.get_task(task_id)

    def resolve_recovery_block(
        self,
        task_id: str,
        *,
        resolution: str,
    ) -> dict[str, Any]:
        targets = {
            "confirm_no_agent": (TaskStatus.RETRY_PENDING, "confirmed_no_agent"),
            "resume": (TaskStatus.RETRY_PENDING, "operator_resumed"),
            "cancel": (TaskStatus.FAILED, "cancelled"),
        }
        if resolution not in targets:
            raise InvalidTaskError(f"Unsupported recovery resolution: {resolution}")
        target, session_status = targets[resolution]
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise InvalidTaskError(f"Unknown task: {task_id}")
            if row["status"] != TaskStatus.RECOVERY_BLOCKED.value:
                raise StateTransitionError(f"Task is not recovery blocked: {task_id}")
            now = utc_now()
            message = (
                "Operator confirmed that no matching agent process is running"
                if resolution == "confirm_no_agent"
                else (
                    "Operator resumed recovery-blocked task after inspection"
                    if resolution == "resume"
                    else "Operator cancelled recovery-blocked task"
                )
            )
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, last_error = ? WHERE task_id = ?",
                (target.value, now, message, task_id),
            )
            connection.execute(
                """
                UPDATE agent_sessions
                SET status = ?, output_summary = ?, heartbeat_at = ?, finished_at = ?
                WHERE task_id = ? AND status = ?
                """,
                (
                    session_status,
                    message,
                    now,
                    now,
                    task_id,
                    TaskStatus.RECOVERY_BLOCKED.value,
                ),
            )
            self._event(
                connection,
                task_id,
                "task_recovery_resolved",
                TaskStatus.RECOVERY_BLOCKED.value,
                target.value,
                {"resolution": resolution, "reason": message},
            )
        return self.get_task(task_id)

    def list_attempts(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM task_attempts WHERE task_id = ? ORDER BY attempt_number",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(
        self,
        task_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 1000)) if limit is not None else None
        with self.connect() as connection:
            if task_id:
                if bounded_limit is None:
                    rows = connection.execute(
                        "SELECT * FROM events WHERE task_id = ? ORDER BY event_id", (task_id,)
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM (SELECT * FROM events WHERE task_id = ? "
                        "ORDER BY event_id DESC LIMIT ?) ORDER BY event_id",
                        (task_id, bounded_limit),
                    ).fetchall()
            else:
                if bounded_limit is None:
                    rows = connection.execute("SELECT * FROM events ORDER BY event_id").fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM (SELECT * FROM events ORDER BY event_id DESC LIMIT ?) "
                        "ORDER BY event_id",
                        (bounded_limit,),
                    ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["payload"] = _loads(value.pop("payload_json"), {})
            result.append(value)
        return result

    def record_event(
        self,
        *,
        task_id: str | None,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction(immediate=True) as connection:
            self._event(
                connection,
                task_id,
                event_type,
                None,
                None,
                payload or {},
            )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        task_id: str | None,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(
                task_id, event_type, from_status, to_status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, event_type, from_status, to_status, _json(payload), utc_now()),
        )
