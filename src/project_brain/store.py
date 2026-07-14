"""Versioned SQLite repository for Project Brain Core state."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import InvalidTaskError, StateTransitionError
from .models import (
    ALLOWED_TRANSITIONS,
    CLAIMABLE_STATUSES,
    CanonicalTask,
    Project,
    TaskStatus,
    parse_timestamp,
    utc_now,
)
from .security import command_contains_secret, contains_known_secret, redact_text
from .schema import MIGRATIONS, SCHEMA_VERSION


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class TaskStore:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, migration in MIGRATIONS.items():
                if version in applied:
                    continue
                connection.executescript(migration)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        with self.connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])

    def register_project(self, project: Project | dict[str, Any]) -> dict[str, Any]:
        record = project.as_record() if isinstance(project, Project) else dict(project)
        commands = [record.get("codex_command") or []]
        commands.extend((record.get("allowed_commands") or {}).values())
        for check in record.get("verification_commands") or []:
            if isinstance(check, list):
                commands.append(check)
            elif isinstance(check, dict):
                commands.append(check.get("command") or check.get("argv") or [])
        if contains_known_secret(record.get("remote_url", "")) or any(
            isinstance(command, list) and command_contains_secret(command)
            for command in commands
        ):
            raise InvalidTaskError("Project configuration contains a credential-like value")
        now = utc_now()
        created_at = str(record.get("created_at") or now)
        updated_at = now
        required = ("project_id", "name", "repo_path", "remote_url", "default_branch", "worktree_root")
        for key in required:
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise InvalidTaskError(f"Project {key} must be a non-empty string")
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, name, repo_path, remote_url, default_branch,
                    worktree_root, codex_command_json, verification_commands_json,
                    allowed_commands_json, auto_push, auto_pr, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name = excluded.name,
                    repo_path = excluded.repo_path,
                    remote_url = excluded.remote_url,
                    default_branch = excluded.default_branch,
                    worktree_root = excluded.worktree_root,
                    codex_command_json = excluded.codex_command_json,
                    verification_commands_json = excluded.verification_commands_json,
                    allowed_commands_json = excluded.allowed_commands_json,
                    auto_push = excluded.auto_push,
                    auto_pr = excluded.auto_pr,
                    updated_at = excluded.updated_at
                """,
                (
                    record["project_id"],
                    record["name"],
                    record["repo_path"],
                    record["remote_url"],
                    record.get("default_branch", "main"),
                    record["worktree_root"],
                    _json(record.get("codex_command", [])),
                    _json(record.get("verification_commands", [])),
                    _json(record.get("allowed_commands", {})),
                    int(bool(record.get("auto_push", True))),
                    int(bool(record.get("auto_pr", True))),
                    created_at,
                    updated_at,
                ),
            )
        return self.get_project(record["project_id"])

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
        return value

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unregistered project: {project_id}")
        return self._project(row)

    def get_project_by_name(self, name: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unregistered project: {name}")
        return self._project(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [self._project(row) for row in rows]

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["acceptance_criteria"] = _loads(
            value.pop("acceptance_criteria_json"), []
        )
        value["payload"] = _loads(value.pop("payload_json"), {})
        value["commit"] = value.pop("commit_sha")
        return value

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
            logical = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? AND dedupe_key = ? AND revision = ?",
                (record["project_id"], record["dedupe_key"], record["revision"]),
            ).fetchone()
            if logical is not None:
                return self._task(logical), False
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (record["project_id"],)
            ).fetchone() is None:
                raise InvalidTaskError(f"Unregistered project: {record['project_id']}")
            if record.get("supersedes"):
                old = connection.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (record["supersedes"],)
                ).fetchone()
                if old is None:
                    raise InvalidTaskError(
                        f"Superseded task does not exist: {record['supersedes']}"
                    )
                if old["project_id"] != record["project_id"] or old["dedupe_key"] != record["dedupe_key"]:
                    raise InvalidTaskError("supersedes must reference the same project and dedupe_key")
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, project_id, dedupe_key, revision, source_type,
                    source_message_id, goal, acceptance_criteria_json, task_type,
                    payload_json, status, attempt_count, created_at, updated_at,
                    expires_at, supersedes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    record["task_id"], record["project_id"], record["dedupe_key"],
                    record["revision"], record["source_type"],
                    record.get("source_message_id"), record["goal"],
                    _json(record.get("acceptance_criteria", [])), record["task_type"],
                    _json(record.get("payload", {})), TaskStatus.PENDING.value,
                    now, now, record.get("expires_at"), record.get("supersedes"),
                ),
            )
            self._event(
                connection,
                record["task_id"],
                "task_created",
                None,
                TaskStatus.PENDING.value,
                {"revision": record["revision"], "source_type": record["source_type"]},
            )
            if record.get("supersedes"):
                old = connection.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (record["supersedes"],)
                ).fetchone()
                if old and old["status"] not in {
                    TaskStatus.ACCEPTED.value,
                    TaskStatus.SUPERSEDED.value,
                }:
                    connection.execute(
                        "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                        (TaskStatus.SUPERSEDED.value, now, old["task_id"]),
                    )
                    self._event(
                        connection,
                        old["task_id"],
                        "task_superseded",
                        old["status"],
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
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, last_error = ? WHERE task_id = ?",
                (target.value, now, redact_text(last_error) if last_error else None, task_id),
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
            attempt_number = int(row["attempt_count"]) + 1
            connection.execute(
                "UPDATE tasks SET status = ?, attempt_count = ?, updated_at = ?, last_error = NULL "
                "WHERE task_id = ? AND status = ?",
                (
                    TaskStatus.RUNNING.value,
                    attempt_number,
                    claimed_at,
                    row["task_id"],
                    row["status"],
                ),
            )
            connection.execute(
                "INSERT INTO task_attempts(task_id, attempt_number, status, started_at) "
                "VALUES (?, ?, 'running', ?)",
                (row["task_id"], attempt_number, claimed_at),
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
                    error_message,
                    utc_now(),
                    task_id,
                    task["attempt_count"],
                ),
            )

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
                    session_id, task_id, adapter, command_json, status, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (session_id, task_id, adapter, _json(command), utc_now()),
            )
            connection.execute(
                "UPDATE tasks SET agent_session_id = ?, updated_at = ? WHERE task_id = ?",
                (session_id, utc_now(), task_id),
            )

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
                "finished_at = ? WHERE session_id = ?",
                (status, exit_code, output_summary, utc_now(), session_id),
            )

    def record_verification(self, task_id: str, result: dict[str, Any]) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO verification_results(
                    task_id, criterion_id, criterion_text, status, evidence_type,
                    evidence_summary, command_json, exit_code, artifact_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    result.get("created_at") or utc_now(),
                ),
            )

    def list_verifications(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM verification_results WHERE task_id = ? ORDER BY verification_id",
                (task_id,),
            ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["command"] = _loads(value.pop("command_json"), None)
            values.append(value)
        return values

    def list_attempts(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM task_attempts WHERE task_id = ? ORDER BY attempt_number",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, task_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if task_id:
                rows = connection.execute(
                    "SELECT * FROM events WHERE task_id = ? ORDER BY event_id", (task_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM events ORDER BY event_id").fetchall()
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
