from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from project_brain.errors import MigrationError
from project_brain.schema import MIGRATION_1, MIGRATION_2, MIGRATION_3, SCHEMA_VERSION
from project_brain.store import TaskStore


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "brain.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_version_one_database_migrates_forward(self) -> None:
        TaskStore(
            self.database, migrations={1: MIGRATION_1}, schema_version=1
        ).initialize()
        store = TaskStore(self.database)
        store.initialize()
        self.assertEqual(store.schema_version(), SCHEMA_VERSION)
        with store.connect() as connection:
            task_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
            }
        self.assertIn("attempt_phase", task_columns)

    def test_version_two_verification_history_is_bound_to_a_migrated_set(self) -> None:
        TaskStore(
            self.database,
            migrations={1: MIGRATION_1, 2: MIGRATION_2},
            schema_version=2,
        ).initialize()
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, name, repo_path, remote_url, default_branch,
                    worktree_root, codex_command_json, verification_commands_json,
                    allowed_commands_json, created_at, updated_at
                ) VALUES (
                    'project', 'project', '/tmp/project', '/tmp/remote.git', 'main',
                    '/tmp/worktrees', '["codex"]', '[]', '{}', '2026-01-01', '2026-01-01'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, project_id, dedupe_key, revision, source_type, goal,
                    acceptance_criteria_json, task_type, payload_json, status,
                    attempt_count, head_sha, commit_sha, attempt_phase,
                    created_at, updated_at
                ) VALUES (
                    'task', 'project', 'task', 1, 'test', 'migrate evidence',
                    '[]', 'codex', '{}', 'retry_pending', 1, ?, ?, 'publication',
                    '2026-01-01', '2026-01-01'
                )
                """,
                ("a" * 40, "a" * 40),
            )
            connection.execute(
                """
                INSERT INTO task_attempts(
                    task_id, attempt_number, status, phase, head_sha, started_at, finished_at
                ) VALUES (
                    'task', 1, 'retry_pending', 'publication', ?,
                    '2026-01-01', '2026-01-01'
                )
                """,
                ("a" * 40,),
            )
            connection.execute(
                """
                INSERT INTO verification_results(
                    task_id, criterion_id, criterion_text, status, evidence_type,
                    evidence_summary, attempt_number, created_at
                ) VALUES (
                    'task', 'check', 'Check', 'passed', 'trusted_project_command',
                    'passed', 1, '2026-01-01'
                )
                """
            )
        store = TaskStore(self.database)
        store.initialize()
        task = store.get_task("task")
        self.assertIsNotNone(task["verification_set_id"])
        verification_set = store.get_verification_set(task["verification_set_id"])
        self.assertEqual(verification_set["canonical_head_sha"], "a" * 40)
        evidence = store.publication_evidence("task")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(
            evidence[0]["verification_set_id"], verification_set["verification_set_id"]
        )

    def test_version_three_agent_sessions_gain_process_identity(self) -> None:
        TaskStore(
            self.database,
            migrations={1: MIGRATION_1, 2: MIGRATION_2, 3: MIGRATION_3},
            schema_version=3,
        ).initialize()
        store = TaskStore(self.database)
        store.initialize()
        with store.connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(agent_sessions)")
            }
        self.assertIn("child_identity_json", columns)

    def test_failed_migration_rolls_back_atomically(self) -> None:
        store = TaskStore(
            self.database,
            migrations={1: MIGRATION_1, 2: "CREATE TABLE partial(value TEXT); INVALID SQL;"},
            schema_version=2,
        )
        with self.assertRaises(sqlite3.DatabaseError):
            store.initialize()
        with sqlite3.connect(self.database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("partial", tables)
        self.assertNotIn("tasks", tables)

    def test_future_schema_is_rejected(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with self.assertRaises(MigrationError):
            TaskStore(self.database).initialize()


if __name__ == "__main__":
    unittest.main()
