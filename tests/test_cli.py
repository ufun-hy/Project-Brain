from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from project_brain.cli import main
from project_brain.locking import RuntimeLock
from project_brain.models import TaskStatus
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "cli")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            codex_command=["git", "--version"],
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def invoke(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--runtime-root", str(self.fixture.runtime.root), *args])
        return code, output.getvalue()

    def test_status_json_shows_stage_project_and_next_action(self) -> None:
        self.fixture.add_task("status-task")
        code, output = self.invoke("status", "--json")
        value = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(value["tasks"][0]["status"], TaskStatus.PENDING.value)
        self.assertEqual(value["tasks"][0]["project"], "project-one")
        self.assertIn("Run project-brain apply", value["tasks"][0]["next_action"])

    def test_projects_and_tasks_commands_support_json(self) -> None:
        self.fixture.add_task("show-task")
        _, projects = self.invoke("projects", "list", "--json")
        self.assertEqual(json.loads(projects)[0]["project_id"], "project-one")
        _, listed = self.invoke("tasks", "list", "--json")
        self.assertEqual(json.loads(listed)[0]["task_id"], "show-task")
        _, shown = self.invoke("tasks", "show", "show-task", "--json")
        value = json.loads(shown)
        self.assertIn("attempts", value)
        self.assertIn("verification", value)
        self.assertIn("events", value)

    def test_health_reports_runtime_database_and_registered_project(self) -> None:
        code, output = self.invoke("health", "--json")
        value = json.loads(output)
        self.assertEqual(code, 0)
        names = {item["name"] for item in value["checks"]}
        self.assertIn("runtime_root", names)
        self.assertIn("database_schema", names)
        self.assertIn("project:project-one", names)

    def test_cleanup_defaults_to_dry_run_and_requires_execute(self) -> None:
        self.fixture.add_task("cleanup-task")
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store)
        record = manager.create(task, self.project)
        self.fixture.store.transition("cleanup-task", TaskStatus.FAILED)
        _, preview = self.invoke("cleanup", "--json")
        self.assertEqual(json.loads(preview)["mode"], "dry_run")
        self.assertTrue(Path(record["path"]).exists())
        _, executed = self.invoke("cleanup", "--execute", "--json")
        self.assertEqual(json.loads(executed)["mode"], "execute")
        self.assertFalse(Path(record["path"]).exists())

    def test_apply_reports_already_running_without_claiming(self) -> None:
        self.fixture.add_task("locked-task")
        with RuntimeLock(self.fixture.runtime.lock_file):
            code, output = self.invoke("apply", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "already_running")
        self.assertEqual(
            self.fixture.store.get_task("locked-task")["status"], TaskStatus.PENDING.value
        )


if __name__ == "__main__":
    unittest.main()
