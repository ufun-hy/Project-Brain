from __future__ import annotations

import json
import unittest

from project_brain.gmail import GmailAdapter, compatibility_task_id
from project_brain.models import TaskStatus

from tests.helpers import CoreFixture


class GmailAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project(name="Project-Brain")
        self.adapter = GmailAdapter(self.fixture.store)

    def tearDown(self) -> None:
        self.fixture.close()

    def test_legacy_message_gets_reproducible_task_id_and_warning(self) -> None:
        message = {
            "message_id": "gmail-message-1",
            "body": json.dumps(
                {
                    "type": "codex",
                    "project": "Project-Brain",
                    "prompt": "Implement safely",
                    "commit_message": "feat: safe",
                }
            ),
        }
        first = self.adapter.import_message(message)
        second = self.adapter.import_message(message)
        expected = compatibility_task_id("gmail-message-1")
        self.assertEqual(first["task_id"], expected)
        self.assertEqual(second["task_id"], expected)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        events = self.fixture.store.list_events(expected)
        self.assertEqual(
            [event["event_type"] for event in events].count("compatibility_warning"), 1
        )

    def test_new_message_preserves_identity_revision_expiry_and_supersedes(self) -> None:
        self.fixture.add_task("old", dedupe_key="flow", revision=1)
        message = {
            "message_id": "gmail-message-2",
            "body": json.dumps(
                {
                    "task_id": "new-task",
                    "project_id": "project-one",
                    "dedupe_key": "flow",
                    "revision": 2,
                    "supersedes": "old",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "type": "write_files",
                    "goal": "Write a file",
                    "acceptance_criteria": ["Review content"],
                    "files": [{"path": "new.txt", "content": "new\n"}],
                }
            ),
        }
        imported = self.adapter.import_message(message)
        task = self.fixture.store.get_task(imported["task_id"])
        self.assertEqual(task["revision"], 2)
        self.assertEqual(task["source_message_id"], "gmail-message-2")
        self.assertEqual(task["supersedes"], "old")
        self.assertEqual(self.fixture.store.get_task("old")["status"], TaskStatus.SUPERSEDED.value)

    def test_scan_imports_multiple_messages_and_does_not_execute(self) -> None:
        messages = [
            {
                "message_id": f"message-{index}",
                "body": json.dumps(
                    {
                        "task_id": f"task-{index}",
                        "project_id": "project-one",
                        "dedupe_key": f"flow-{index}",
                        "revision": 1,
                        "type": "codex",
                        "goal": f"Goal {index}",
                        "prompt": "Do work",
                    }
                ),
            }
            for index in range(2)
        ]
        results = self.adapter.import_messages(messages)
        self.assertEqual(sum(item["created"] for item in results), 2)
        self.assertEqual(
            {task["status"] for task in self.fixture.store.list_tasks()},
            {TaskStatus.PENDING.value},
        )

    def test_invalid_message_does_not_prevent_later_import(self) -> None:
        results = self.adapter.import_messages(
            [
                {"message_id": "bad", "body": "not json"},
                {
                    "message_id": "good",
                    "body": json.dumps(
                        {
                            "task_id": "good-task",
                            "project_id": "project-one",
                            "dedupe_key": "good",
                            "revision": 1,
                            "type": "codex",
                            "goal": "Good",
                            "prompt": "Good",
                        }
                    ),
                },
            ]
        )
        self.assertEqual(results[0]["status"], "rejected")
        self.assertTrue(results[1]["created"])


if __name__ == "__main__":
    unittest.main()
