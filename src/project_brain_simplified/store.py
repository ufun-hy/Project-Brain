from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import Project, utc_now, validate_ponytail_mode

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  repo_path TEXT NOT NULL,
  default_branch TEXT NOT NULL,
  codex_command_json TEXT NOT NULL,
  checks_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  request_key TEXT,
  goal TEXT NOT NULL,
  prompt TEXT NOT NULL,
  ponytail_mode TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  worker_pid INTEGER,
  codex_supervisor_pid INTEGER,
  base_sha TEXT,
  branch TEXT,
  worktree_path TEXT,
  codex_exit_code INTEGER,
  codex_summary TEXT,
  changed_files_json TEXT NOT NULL DEFAULT '[]',
  diff_text TEXT NOT NULL DEFAULT '',
  diff_size INTEGER NOT NULL DEFAULT 0,
  diff_truncated INTEGER NOT NULL DEFAULT 0,
  checks_json TEXT NOT NULL DEFAULT '[]',
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at DESC);
PRAGMA user_version = 1;
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


class Store:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.database.parent, 0o700)
        except OSError:
            pass
        conn = sqlite3.connect(self.database, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1}:
                raise RuntimeError(f"Unsupported simplified schema version: {version}")
            if version == 0:
                existing = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise RuntimeError("Database is not a fresh simplified runtime; refusing migration")
            conn.executescript(SCHEMA)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "ponytail_mode" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN ponytail_mode TEXT")

    def register_project(self, project: Project) -> dict[str, Any]:
        project.validate()
        now = utc_now()
        with self.transaction(immediate=True) as conn:
            existing = conn.execute(
                "SELECT created_at FROM projects WHERE project_id=?", (project.project_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO projects(project_id,name,repo_path,default_branch,codex_command_json,checks_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(project_id) DO UPDATE SET
                  name=excluded.name,
                  repo_path=excluded.repo_path,
                  default_branch=excluded.default_branch,
                  codex_command_json=excluded.codex_command_json,
                  checks_json=excluded.checks_json,
                  updated_at=excluded.updated_at
                """,
                (
                    project.project_id,
                    project.name,
                    str(Path(project.repo_path).expanduser().resolve()),
                    project.default_branch,
                    _json(project.codex_command),
                    _json(project.checks),
                    created_at,
                    now,
                ),
            )
        return self.get_project(project.project_id)

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["codex_command"] = _loads(value.pop("codex_command_json"), [])
        value["checks"] = _loads(value.pop("checks_json"), [])
        return value

    def get_project(self, project_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown project: {project_id}")
        return self._project(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [self._project(row) for row in rows]

    def create_task(
        self, *, project_id: str, goal: str, prompt: str, ponytail_mode: str | None = None
    ) -> dict[str, Any]:
        task, _ = self.create_or_get_task(
            project_id=project_id,
            goal=goal,
            prompt=prompt,
            request_key=None,
            ponytail_mode=ponytail_mode,
        )
        return task

    def create_or_get_task(
        self,
        *,
        project_id: str,
        goal: str,
        prompt: str,
        request_key: str | None,
        ponytail_mode: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        self.get_project(project_id)
        if not goal.strip() or not prompt.strip():
            raise ValueError("goal and prompt must be non-empty")
        if ponytail_mode is not None:
            validate_ponytail_mode(ponytail_mode)
        now = utc_now()
        with self.transaction(immediate=True) as conn:
            existing = None
            if request_key is not None:
                existing = conn.execute(
                    "SELECT * FROM tasks WHERE request_key=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
                    (request_key,),
                ).fetchone()
            if existing is not None:
                return self._task(existing), False
            task_id = f"task-{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO tasks(task_id,project_id,request_key,goal,prompt,ponytail_mode,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    project_id,
                    request_key,
                    goal.strip(),
                    prompt.strip(),
                    ponytail_mode,
                    "queued",
                    now,
                ),
            )
        return self.get_task(task_id), True

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["changed_files"] = _loads(value.pop("changed_files_json"), [])
        value["checks"] = _loads(value.pop("checks_json"), [])
        return value

    def get_task(self, task_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return self._task(row)

    def list_tasks(self, *, project_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with closing(self.connect()) as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._task(row) for row in rows]

    def claim_task(self, task_id: str, *, pid: int) -> dict[str, Any]:
        with self.transaction(immediate=True) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown task: {task_id}")
            if row["status"] != "queued":
                raise RuntimeError(f"Task is not queued: {task_id} ({row['status']})")
            conn.execute(
                "UPDATE tasks SET status='running',started_at=?,worker_pid=? WHERE task_id=?",
                (utc_now(), int(pid), task_id),
            )
        return self.get_task(task_id)

    def record_execution_identity(
        self, task_id: str, *, base_sha: str, branch: str, worktree_path: str
    ) -> None:
        with self.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE tasks SET base_sha=?,branch=?,worktree_path=? WHERE task_id=?",
                (base_sha, branch, worktree_path, task_id),
            )

    def record_codex_supervisor_pid(self, task_id: str, *, pid: int) -> None:
        with self.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE tasks SET codex_supervisor_pid=? WHERE task_id=?",
                (int(pid), task_id),
            )

    def record_worker_pid(self, task_id: str, *, pid: int) -> None:
        """Record a launched worker without changing the user-visible state."""
        with self.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT status,worker_pid FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown task: {task_id}")
            if row["status"] == "queued" and row["worker_pid"] is None:
                conn.execute("UPDATE tasks SET worker_pid=? WHERE task_id=?", (int(pid), task_id))

    def fail_running_task(self, task_id: str, *, error: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown task: {task_id}")
            if row["status"] not in {"queued", "running"}:
                return self.get_task(task_id)
            conn.execute(
                "UPDATE tasks SET status='failed',finished_at=?,error=? WHERE task_id=?",
                (utc_now(), error[-10000:], task_id),
            )
        return self.get_task(task_id)

    def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        codex_exit_code: int | None,
        codex_summary: str,
        changed_files: list[str],
        diff_text: str,
        checks: list[dict[str, Any]],
        error: str | None,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed"}:
            raise ValueError(f"Invalid terminal status: {status}")
        with self.transaction(immediate=True) as conn:
            current = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if current is None:
                raise KeyError(f"Unknown task: {task_id}")
            if current["status"] != "running":
                raise RuntimeError(f"Task is not running: {task_id} ({current['status']})")
            conn.execute(
                """
                UPDATE tasks SET status=?,finished_at=?,codex_exit_code=?,codex_summary=?,
                  changed_files_json=?,diff_text=?,diff_size=?,diff_truncated=?,checks_json=?,error=?
                WHERE task_id=?
                """,
                (
                    status,
                    utc_now(),
                    codex_exit_code,
                    codex_summary[-20000:],
                    _json(changed_files),
                    diff_text[-120000:],
                    len(diff_text),
                    int(len(diff_text) > 120000),
                    _json(checks),
                    error[-10000:] if error else None,
                    task_id,
                ),
            )
        return self.get_task(task_id)
