from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from project_brain.cli import main
from project_brain.errors import InvalidTaskError
from project_brain.models import TaskStatus

from tests.helpers import CoreFixture


class ProjectLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.project = self.fixture.add_project()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_pause_blocks_only_new_intake_and_resume_restores_it(self) -> None:
        existing = self.fixture.add_task("existing")
        paused = self.fixture.store.set_project_accepting("project-one", False)
        self.assertFalse(paused["accepting_tasks"])
        self.assertEqual(self.fixture.store.get_task(existing["task_id"])["status"], "pending")
        with self.assertRaises(InvalidTaskError):
            self.fixture.add_task("blocked")
        resumed = self.fixture.store.set_project_accepting("project-one", True)
        self.assertTrue(resumed["accepting_tasks"])
        self.fixture.add_task("after-resume")

    def test_remove_is_soft_preserves_history_and_requires_terminal_tasks(self) -> None:
        self.fixture.add_task("history")
        with self.assertRaises(InvalidTaskError):
            self.fixture.store.remove_project_registration("project-one")
        self.fixture.store.claim_next()
        self.fixture.store.transition("history", TaskStatus.FAILED)
        removed = self.fixture.store.remove_project_registration("project-one")
        self.assertFalse(removed["registered"])
        self.assertFalse(removed["accepting_tasks"])
        self.assertEqual(self.fixture.store.get_task("history")["status"], "failed")
        self.assertEqual(self.fixture.store.list_projects(), [])
        with self.assertRaises(InvalidTaskError):
            self.fixture.store.get_project("project-one")
        self.assertFalse(
            self.fixture.store.get_project("project-one", include_removed=True)["registered"]
        )

        restored = self.fixture.store.register_project(self.project)
        self.assertTrue(restored["registered"])
        self.assertTrue(restored["accepting_tasks"])

    def test_cli_lifecycle_requires_plan_then_explicit_execute(self) -> None:
        def invoke(*arguments: str) -> dict:
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(
                    ["--runtime-root", str(self.fixture.runtime.root), *arguments, "--json"]
                )
            self.assertEqual(code, 0)
            return json.loads(stream.getvalue())

        plan = invoke("projects", "pause", "project-one")
        self.assertEqual(plan["status"], "planned")
        self.assertTrue(self.fixture.store.get_project("project-one")["accepting_tasks"])
        applied = invoke("projects", "pause", "project-one", "--execute")
        self.assertEqual(applied["status"], "applied")
        self.assertFalse(applied["project"]["accepting_tasks"])


if __name__ == "__main__":
    unittest.main()
