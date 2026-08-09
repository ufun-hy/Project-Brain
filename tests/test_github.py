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
            "remote_url": "git@github.com:ufun-hy/Project-Brain.git",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_existing_open_pr_is_reused(self, origin_check, run_command, git_command) -> None:
        git_command.side_effect = self._git_result
        run_command.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps([self._existing_pr("https://example.test/pr/7")]),
            "",
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
        title = create_args[create_args.index("--title") + 1]
        body = create_args[create_args.index("--body") + 1]
        self.assertEqual(title, "Review task")
        self.assertIn("## Changed files", body)
        self.assertIn("## Acceptance criteria", body)
        self.assertIn("## Verification", body)
        self.assertIn("## Known gaps / review boundary", body)
        self.assertIn("remains Draft", body)
        self.assertEqual(origin_check.call_count, 2)

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_generated_pr_metadata_is_bounded_and_traceable(
        self, origin_check, run_command, git_command
    ) -> None:
        git_command.side_effect = self._git_result
        run_command.side_effect = [
            subprocess.CompletedProcess([], 0, "[]", ""),
            subprocess.CompletedProcess([], 0, "https://example.test/pr/11\n", ""),
        ]
        task = {
            **self.task,
            "goal": "任务名称：Web Task Intake v1\n\n目标：不要把整段正文当标题。",
            "source_type": "mcp",
            "acceptance_criteria": [
                {"id": "AC-01", "text": "Analyze stays read-only"}
            ],
            "publication_context": {
                "changed_files": ["src/project_brain/engine.py"],
                "verification_evidence": [
                    {
                        "verification_id": "core-tests",
                        "criterion_id": "AC-01",
                        "status": "passed",
                        "evidence_summary": "Core tests passed",
                    }
                ],
            },
        }
        GitHubAdapter().publish(task=task, project=self.project, worktree=self.worktree)
        create_args = run_command.call_args_list[1].args[0]
        title = create_args[create_args.index("--title") + 1]
        body = create_args[create_args.index("--body") + 1]
        self.assertEqual(title, "Web Task Intake v1")
        self.assertLessEqual(len(title), 120)
        self.assertIn("`src/project_brain/engine.py`", body)
        self.assertIn("[x] `AC-01`", body)
        self.assertIn("Core tests passed", body)
        self.assertIn("Real ChatGPT web ingress acceptance is tracked separately", body)

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_existing_ready_pr_blocks_publication_state(
        self, origin_check, run_command, git_command
    ) -> None:
        git_command.side_effect = self._git_result
        run_command.return_value = subprocess.CompletedProcess(
            [],
            0,
            json.dumps([self._existing_pr("https://example.test/pr/9", is_draft=False)]),
            "",
        )
        with self.assertRaises(TaskHistoryError):
            GitHubAdapter().publish(
                task=self.task, project=self.project, worktree=self.worktree
            )

    @patch("project_brain.github.git")
    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_existing_pr_must_match_base_head_sha_and_repository(
        self, origin_check, run_command, git_command
    ) -> None:
        git_command.side_effect = self._git_result
        mismatches = {
            "base": {"baseRefName": "release"},
            "head": {"headRefName": "brain/other"},
            "sha": {"headRefOid": "b" * 40},
            "repository": {
                "headRepository": {"nameWithOwner": "someone-else/Project-Brain"}
            },
        }
        for label, changed in mismatches.items():
            with self.subTest(label=label):
                candidate = self._existing_pr("https://example.test/pr/10")
                candidate.update(changed)
                run_command.return_value = subprocess.CompletedProcess(
                    [], 0, json.dumps([candidate]), ""
                )
                with self.assertRaises(TaskHistoryError):
                    GitHubAdapter().publish(
                        task=self.task,
                        project=self.project,
                        worktree=self.worktree,
                    )

    def _existing_pr(self, url: str, *, is_draft: bool = True) -> dict:
        return {
            "url": url,
            "isDraft": is_draft,
            "baseRefName": "main",
            "headRefName": self.task["branch"],
            "headRefOid": self.task["commit"],
            "headRepository": {"nameWithOwner": "ufun-hy/Project-Brain"},
        }

    def _git_result(self, *args, **_):
        if "ls-remote" in args:
            output = f"{self.task['commit']}\trefs/heads/{self.task['branch']}\n"
        else:
            output = ""
        return subprocess.CompletedProcess(args, 0, output, "")


if __name__ == "__main__":
    unittest.main()
