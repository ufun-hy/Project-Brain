from __future__ import annotations

import json
import sys
import unittest

from project_brain.errors import InvalidTaskError
from project_brain.ingress import TaskImporter

from tests.helpers import CoreFixture


class CanonicalIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project(
            verification_commands=[
                {
                    "id": "unit-tests",
                    "text": "Run unit tests",
                    "command": [sys.executable, "-c", "pass"],
                    "always_run": False,
                }
            ]
        )
        self.importer = TaskImporter(self.fixture.store)

    def tearDown(self) -> None:
        self.fixture.close()

    def envelope(self, **changes):
        value = {
            "task_id": "external-task",
            "project_id": "project-one",
            "dedupe_key": "external-task",
            "revision": 1,
            "source_type": "adapter",
            "goal": "Exercise source-neutral ingress",
            "task_type": "codex",
            "acceptance_criteria": [
                {
                    "id": "core-tests",
                    "text": "Core tests pass",
                    "verification_id": "unit-tests",
                }
            ],
            "payload": {"prompt": "Implement the task"},
        }
        value.update(changes)
        return value

    def test_import_file_is_source_neutral_and_idempotent(self) -> None:
        source = self.fixture.root / "canonical-task.json"
        source.write_text(json.dumps(self.envelope()), encoding="utf-8")
        first, created = self.importer.import_file(source)
        second, duplicate_created = self.importer.import_file(source)
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first["task_id"], second["task_id"])

    def test_external_command_and_argv_are_rejected(self) -> None:
        for field in ("command", "argv"):
            criterion = {"id": "unsafe", "text": "unsafe", field: ["sh", "-c", "id"]}
            with self.subTest(field=field), self.assertRaises(InvalidTaskError):
                self.importer.import_value(
                    self.envelope(acceptance_criteria=[criterion])
                )

    def test_unknown_verification_id_is_rejected(self) -> None:
        with self.assertRaises(InvalidTaskError):
            self.importer.import_value(
                self.envelope(
                    acceptance_criteria=[
                        {"id": "unknown", "text": "Unknown", "verification_id": "not-registered"}
                    ]
                )
            )

    def test_external_ids_cannot_escape_runtime_namespaces(self) -> None:
        cases = (
            {"task_id": "../escape"},
            {"task_id": "/absolute"},
            {"dedupe_key": "a/b"},
            {"acceptance_criteria": [{"id": "../criterion", "text": "bad"}]},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(InvalidTaskError):
                self.importer.import_value(self.envelope(**changes))


if __name__ == "__main__":
    unittest.main()
