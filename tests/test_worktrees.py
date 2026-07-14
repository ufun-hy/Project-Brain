from __future__ import annotations

import os
import unittest
from pathlib import Path

from project_brain.errors import InvalidPathError, WorktreeError
from project_brain.models import TaskStatus
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone, git, run


class WorktreeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "one")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo), remote_url=str(self.remote)
        )
        self.manager = WorktreeManager(self.fixture.store, self.fixture.runtime)

    def tearDown(self) -> None:
        self.fixture.close()

    def _running_task(self, task_id: str = "task-one") -> dict:
        self.fixture.add_task(task_id)
        claimed = self.fixture.store.claim_next()
        assert claimed
        return claimed

    def test_creates_task_from_clean_main_checkout(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        path = Path(record["path"])
        self.assertTrue(path.is_dir())
        self.assertEqual(git(path, "branch", "--show-current").stdout.strip(), "brain/task-one")
        self.assertEqual(git(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_dirty_main_checkout_does_not_block_or_change_task_creation(self) -> None:
        (self.repo / "human-notes.txt").write_text("do not touch\n", encoding="utf-8")
        task = self._running_task()
        record = self.manager.create(task, self.project)
        self.assertTrue(Path(record["path"]).exists())
        self.assertEqual((self.repo / "human-notes.txt").read_text(encoding="utf-8"), "do not touch\n")
        self.assertIn("human-notes.txt", git(self.repo, "status", "--porcelain").stdout)
        self.assertEqual(git(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_task_uses_latest_remote_default_branch_without_updating_main_checkout(self) -> None:
        publisher = self.fixture.root / "publisher"
        run("git", "clone", str(self.remote), str(publisher))
        git(publisher, "checkout", "-B", "main", "origin/main")
        git(publisher, "config", "user.email", "test@example.com")
        git(publisher, "config", "user.name", "Project Brain Test")
        (publisher / "remote-new.txt").write_text("latest\n", encoding="utf-8")
        git(publisher, "add", ".")
        git(publisher, "commit", "-m", "remote update")
        git(publisher, "push", "origin", "main")
        original_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        task = self._running_task()
        record = self.manager.create(task, self.project)
        self.assertTrue((Path(record["path"]) / "remote-new.txt").exists())
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), original_main)

    def test_fetch_failure_is_classified_and_does_not_switch_main(self) -> None:
        git(self.repo, "remote", "set-url", "origin", str(self.fixture.root / "missing.git"))
        task = self._running_task()
        with self.assertRaises(WorktreeError):
            self.manager.create(task, self.project)
        self.assertEqual(git(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_existing_remote_task_branch_is_never_overwritten(self) -> None:
        git(self.repo, "branch", "brain/task-one")
        git(self.repo, "push", "origin", "brain/task-one")
        git(self.repo, "branch", "-D", "brain/task-one")
        task = self._running_task()
        with self.assertRaises(WorktreeError):
            self.manager.create(task, self.project)
        self.assertFalse(Path(self.project["worktree_root"], "task-one").exists())
        self.assertEqual(git(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_two_projects_use_separate_roots(self) -> None:
        second_repo, second_remote = create_remote_clone(self.fixture.root, "two")
        second_project = self.fixture.add_project(
            "project-two", repo_path=str(second_repo), remote_url=str(second_remote)
        )
        first_task = self._running_task("one-task")
        first = self.manager.create(first_task, self.project)
        # The first task is already running, so prepare the second as an independent claimed record.
        self.fixture.add_task("two-task", project_id="project-two")
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE tasks SET status = 'running', attempt_count = 1 WHERE task_id = 'two-task'"
            )
        second_task = self.fixture.store.get_task("two-task")
        second = self.manager.create(second_task, second_project)
        self.assertNotEqual(Path(first["path"]).parents[0], Path(second["path"]).parents[0])
        (Path(first["path"]) / "only-one.txt").write_text("one\n", encoding="utf-8")
        self.assertFalse((Path(second["path"]) / "only-one.txt").exists())

    def test_path_outside_registered_root_is_rejected(self) -> None:
        task = self._running_task()
        outside = self.fixture.root / "outside"
        outside.mkdir()
        self.fixture.store.record_worktree(
            task_id=task["task_id"],
            project_id=task["project_id"],
            path=str(outside),
            branch="brain/task-one",
            base_sha="a" * 40,
            owner_pid=None,
        )
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        with self.assertRaises(InvalidPathError):
            self.manager.cleanup_task(task["task_id"], dry_run=False)

    def test_symlink_escape_is_rejected(self) -> None:
        task = self._running_task()
        outside = self.fixture.root / "outside-target"
        outside.mkdir()
        root = Path(self.project["worktree_root"])
        root.mkdir(parents=True, exist_ok=True)
        link = root / "task-one"
        link.symlink_to(outside, target_is_directory=True)
        self.fixture.store.record_worktree(
            task_id=task["task_id"],
            project_id=task["project_id"],
            path=str(link),
            branch="brain/task-one",
            base_sha="b" * 40,
            owner_pid=None,
        )
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        with self.assertRaises(InvalidPathError):
            self.manager.cleanup_task(task["task_id"], dry_run=False)
        self.assertTrue(outside.exists())

    def test_active_task_is_retained_by_cleanup(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        with self.assertRaises(WorktreeError):
            self.manager.cleanup_task(task["task_id"], dry_run=False)
        self.assertTrue(Path(record["path"]).exists())

    def test_existing_task_worktree_must_match_registered_head_before_reuse(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        worktree = Path(record["path"])
        (worktree / "untrusted.txt").write_text("unexpected\n", encoding="utf-8")
        git(worktree, "add", ".")
        git(worktree, "commit", "-m", "unexpected commit")
        with self.assertRaises(WorktreeError):
            self.manager.create(self.fixture.store.get_task(task["task_id"]), self.project)

    def test_terminal_task_can_be_cleaned_and_pruned(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        result = self.manager.cleanup_task(task["task_id"], dry_run=False)
        self.assertEqual(result["action"], "cleaned")
        self.assertFalse(Path(record["path"]).exists())
        self.assertEqual(self.fixture.store.get_worktree(task["task_id"])["status"], "cleaned")
        self.assertNotIn("brain/task-one", git(self.repo, "branch", "--list").stdout)

    def test_live_foreign_owner_prevents_terminal_cleanup(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = ? WHERE task_id = ?",
                (os.getppid(), task["task_id"]),
            )
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        with self.assertRaises(WorktreeError):
            self.manager.cleanup_task(task["task_id"], dry_run=False)
        self.assertTrue(Path(record["path"]).exists())

    def test_startup_cleanup_removes_terminal_worktree_with_dead_owner(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = ?",
                (task["task_id"],),
            )
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        results = self.manager.cleanup_stale(dry_run=False)
        cleaned = next(item for item in results if item["task_id"] == task["task_id"])
        self.assertEqual(cleaned["action"], "cleaned")
        self.assertFalse(Path(record["path"]).exists())

    def test_cleanup_never_deletes_pushed_remote_branch(self) -> None:
        task = self._running_task()
        record = self.manager.create(task, self.project)
        worktree = Path(record["path"])
        (worktree / "pushed.txt").write_text("pushed\n", encoding="utf-8")
        git(worktree, "add", ".")
        git(worktree, "commit", "-m", "pushed task")
        git(worktree, "push", "-u", "origin", record["branch"])
        self.fixture.store.transition(task["task_id"], TaskStatus.FAILED)
        self.manager.cleanup_task(task["task_id"], dry_run=False)
        remote = git(
            self.repo,
            "ls-remote",
            "--heads",
            "origin",
            record["branch"],
        ).stdout
        self.assertIn(record["branch"], remote)


if __name__ == "__main__":
    unittest.main()
