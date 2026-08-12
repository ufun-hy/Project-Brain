from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from project_brain.errors import (
    ExternalCommandError,
    PublicationConflictError,
    TaskHistoryError,
    TransientTaskError,
)
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

    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_remote_drift_is_rejected_before_push(
        self, origin_check, run_command
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def drifted_git(_repo, *args, **kwargs):
            calls.append(tuple(args))
            if "ls-remote" in args:
                return subprocess.CompletedProcess(
                    [], 0, f"{'b' * 40}\trefs/heads/{self.task['branch']}\n", ""
                )
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("project_brain.github.git", side_effect=drifted_git):
            with self.assertRaises(PublicationConflictError) as raised:
                GitHubAdapter().publish(
                    task={**self.task, "local_candidate_sha": "c" * 40},
                    project=self.project,
                    worktree=self.worktree,
                )
        self.assertEqual(raised.exception.category, "publication_conflict")
        self.assertEqual(raised.exception.conflict["observed_remote_head_sha"], "b" * 40)
        self.assertFalse(any("push" in call for call in calls))
        self.assertFalse(any("--force" in call for call in calls))

    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_missing_remote_branch_is_fail_closed_after_published_head(
        self, origin_check, run_command
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def missing_git(_repo, *args, **kwargs):
            calls.append(tuple(args))
            if "ls-remote" in args:
                return subprocess.CompletedProcess([], 0, "", "")
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("project_brain.github.git", side_effect=missing_git):
            with self.assertRaises(PublicationConflictError) as raised:
                GitHubAdapter().publish(
                    task={
                        **self.task,
                        "canonical_published_head_sha": self.task["commit"],
                        "local_candidate_sha": "c" * 40,
                    },
                    project=self.project,
                    worktree=self.worktree,
                )
        self.assertEqual(raised.exception.category, "publication_conflict")
        self.assertEqual(raised.exception.conflict["observed_remote_head_sha"], "")
        self.assertFalse(any("push" in call for call in calls))
        self.assertEqual(run_command.call_count, 0)

    @patch("project_brain.github.assert_registered_origin")
    def test_push_success_pr_lookup_failure_then_candidate_retry_completes_pr(
        self, origin_check
    ) -> None:
        candidate = "c" * 40
        expected = self.task["commit"]
        remote_heads = iter([expected, candidate, candidate])
        git_calls: list[tuple[str, ...]] = []

        def publishing_git(_repo, *args, **kwargs):
            git_calls.append(tuple(args))
            if "ls-remote" in args:
                remote = next(remote_heads)
                return subprocess.CompletedProcess(
                    [], 0, f"{remote}\trefs/heads/{self.task['branch']}\n", ""
                )
            return subprocess.CompletedProcess([], 0, "", "")

        existing = self._existing_pr("https://example.test/pr/retry")
        existing["headRefOid"] = candidate
        run_command = Mock()
        run_command.side_effect = [
            ExternalCommandError("temporary Draft PR lookup failure", returncode=1),
            subprocess.CompletedProcess([], 0, json.dumps([existing]), ""),
        ]
        task = {
            **self.task,
            "canonical_published_head_sha": expected,
            "local_candidate_sha": candidate,
        }
        with patch("project_brain.github.git", side_effect=publishing_git), patch(
            "project_brain.github.run_command", run_command
        ):
            with self.assertRaises(TransientTaskError):
                GitHubAdapter().publish(
                    task=task, project=self.project, worktree=self.worktree
                )
            result = GitHubAdapter().publish(
                task=task, project=self.project, worktree=self.worktree
            )
        self.assertTrue(result["pushed"])
        self.assertTrue(result["resumed"])
        self.assertEqual(result["pr_url"], existing["url"])
        self.assertEqual(run_command.call_count, 2)
        self.assertEqual(
            sum(1 for call in git_calls if "push" in call),
            1,
        )
        self.assertFalse(any("--force" in call for call in git_calls))

    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_retry_third_party_drift_is_conflict_not_candidate_resume(
        self, origin_check, run_command
    ) -> None:
        def drifted_git(_repo, *args, **kwargs):
            if "ls-remote" in args:
                return subprocess.CompletedProcess(
                    [], 0, f"{'b' * 40}\trefs/heads/{self.task['branch']}\n", ""
                )
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("project_brain.github.git", side_effect=drifted_git):
            with self.assertRaises(PublicationConflictError) as raised:
                GitHubAdapter().publish(
                    task={
                        **self.task,
                        "canonical_published_head_sha": "a" * 40,
                        "local_candidate_sha": "c" * 40,
                    },
                    project=self.project,
                    worktree=self.worktree,
                )
        self.assertEqual(raised.exception.conflict["observed_remote_head_sha"], "b" * 40)
        self.assertEqual(run_command.call_count, 0)
        self.assertFalse(run_command.called)

    @patch("project_brain.github.run_command")
    @patch("project_brain.github.assert_registered_origin")
    def test_non_fast_forward_rechecks_remote_without_force_push(
        self, origin_check, run_command
    ) -> None:
        ls_remote_calls = 0
        calls: list[tuple[str, ...]] = []

        def raced_git(_repo, *args, **kwargs):
            nonlocal ls_remote_calls
            calls.append(tuple(args))
            if "ls-remote" in args:
                ls_remote_calls += 1
                remote = "a" * 40 if ls_remote_calls == 1 else "b" * 40
                return subprocess.CompletedProcess(
                    [], 0, f"{remote}\trefs/heads/{self.task['branch']}\n", ""
                )
            if "push" in args:
                raise ExternalCommandError("non-fast-forward", returncode=1)
            return subprocess.CompletedProcess([], 0, "", "")

        with patch("project_brain.github.git", side_effect=raced_git):
            with self.assertRaises(PublicationConflictError):
                GitHubAdapter().publish(
                    task={**self.task, "local_candidate_sha": "c" * 40},
                    project=self.project,
                    worktree=self.worktree,
                )
        self.assertFalse(any("--force" in call for call in calls))

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
