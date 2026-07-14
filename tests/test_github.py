from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_brain.errors import TaskHistoryError
from project_brain.github import GitHubAdapter


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temp.name)
        self.task = {
            "task_id": "task",
            "branch": "brain/task",
            "goal": "Review task",
            "source_type": "test",
            "payload": {},
            "pr_url": None,
            "commit": "a" * 40,
        }
        self.project = {
            "default_branch": "main",
            "auto_pr": True,
            "remote_url": "https://example.test/repo.git",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_existing_open_pr_is_reused(self, origin_check, run_command, git_command) -> None:
        git_command.side_effect = self._git_result
        run_command.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps([{"url": "https://example.test/pr/7", "isDraft": True}]), ""
        )
        result = GitHubAdapter().publish(
            task=self.task, project=self.project, worktree=self.worktree
        )
        self.assertEqual(result["pr_url"], "https://example.test/pr/7")
        self.assertEqual(run_command.call_count, 1)
        self.assertEqual(origin_check.call_count, 2)

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_new_pr_is_always_draft(self, origin_check, run_command, git_command) -> None:
        git_command.side_effect = self._git_result
        run_command.side_effect = [
            subprocess.CompletedProcess([], 0, "[]", ""),
            subprocess.CompletedProcess([], 0, "https://example.test/pr/8\n", ""),
        ]
        result = GitHubAdapter().publish(
            task=self.task, project=self.project, worktree=self.worktree
        )
        self.assertEqual(result["pr_url"], "https://example.test/pr/8")
        create_args = run_command.call_args_list[1].args[0]
        self.assertIn("--draft", create_args)
        self.assertNotIn("merge", create_args)
        self.assertEqual(origin_check.call_count, 2)

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_existing_ready_pr_blocks_publication_state(
        self, origin_check, run_command, git_command
    ) -> None:
        git_command.side_effect = self._git_result
        run_command.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps([{"url": "https://example.test/pr/9", "isDraft": False}]), ""
        )
        with self.assertRaises(TaskHistoryError):
            GitHubAdapter().publish(
                task=self.task, project=self.project, worktree=self.worktree
            )

    def _git_result(self, *args, **_):
        if "ls-remote" in args:
            output = f"{self.task['commit']}\trefs/heads/{self.task['branch']}\n"
        else:
            output = ""
        return subprocess.CompletedProcess(args, 0, output, "")


if __name__ == "__main__":
    unittest.main()
