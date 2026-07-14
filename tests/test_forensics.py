from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from project_brain.forensics import TerminalWorktreeReconciler
from project_brain.models import TaskStatus
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone


class ForensicCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "forensics")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo), remote_url=str(self.remote)
        )
        self.manager = WorktreeManager(self.fixture.store, self.fixture.runtime)

    def tearDown(self) -> None:
        self.fixture.close()

    def test_archive_failure_retains_failed_worktree(self) -> None:
        self.fixture.add_task("archive-failure")
        task = self.fixture.store.claim_next()
        record = self.manager.create(task, self.project)
        self.fixture.store.transition("archive-failure", TaskStatus.FAILED)
        archiver = Mock()
        archiver.capture.side_effect = OSError("archive storage unavailable")

        results = TerminalWorktreeReconciler(
            self.fixture.store,
            self.fixture.runtime,
            self.manager,
            archiver=archiver,
        ).reconcile(execute=True)

        self.assertEqual(results[0]["action"], "retained")
        self.assertIn("archive storage unavailable", results[0]["reason"])
        self.assertTrue(Path(record["path"]).exists())
        self.assertEqual(
            self.fixture.store.get_worktree("archive-failure")["status"], "active"
        )


if __name__ == "__main__":
    unittest.main()
