from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        }
        self.project = {"default_branch": "main", "auto_pr": True}

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    def test_existing_open_pr_is_reused(self, run_command, git_command) -> None:
        git_command.return_value = subprocess.CompletedProcess([], 0, "", "")
        run_command.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps([{"url": "https://example.test/pr/7"}]), ""
        )
        result = GitHubAdapter().publish(
            task=self.task, project=self.project, worktree=self.worktree
        )
        self.assertEqual(result["pr_url"], "https://example.test/pr/7")
        self.assertEqual(run_command.call_count, 1)

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    def test_new_pr_is_always_draft(self, run_command, git_command) -> None:
        git_command.return_value = subprocess.CompletedProcess([], 0, "", "")
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


if __name__ == "__main__":
    unittest.main()
