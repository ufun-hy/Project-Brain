from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from project_brain.errors import MigrationError
from project_brain.schema import MIGRATION_1, SCHEMA_VERSION
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
