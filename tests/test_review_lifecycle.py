from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.engine import TaskEngine
from project_brain.models import AttemptPhase, TaskStatus

from tests.helpers import CoreFixture, create_remote_clone, git


class ReviewLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "review")
        script = (
            "import pathlib,sys; "
            "pathlib.Path('prompt.txt').write_text(sys.stdin.read(), encoding='utf-8')"
        )
        self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            codex_command=[sys.executable, "-c", script],
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def test_needs_changes_reruns_codex_with_commit_bound_findings(self) -> None:
        self.fixture.add_task(
            "review-task",
            payload={"prompt": "Initial implementation prompt", "commit_message": "canonical"},
        )
        first = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        first_commit = first["task"]["commit"]
        review = self.fixture.store.record_review(
            "review-task",
            verdict="needs_changes",
            head_sha=first_commit,
            findings=[
                {
                    "severity": "blocker",
                    "file": "prompt.txt",
                    "evidence": "The first attempt omitted recovery behavior.",
                    "requirement": "Add deterministic recovery behavior.",
                }
            ],
        )
        changed = self.fixture.store.transition(
            "review-task", TaskStatus.NEEDS_CHANGES
        )
        self.assertEqual(changed["attempt_phase"], AttemptPhase.IMPLEMENTATION.value)
        self.assertEqual(review["head_sha"], first_commit)

        second = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        second_commit = second["task"]["commit"]
        worktree = Path(second["task"]["worktree_path"])
        prompt = (worktree / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("Active review findings", prompt)
        self.assertIn("Add deterministic recovery behavior", prompt)
        self.assertNotEqual(first_commit, second_commit)
        self.assertEqual(
            git(worktree, "merge-base", "--is-ancestor", first_commit, second_commit, check=False).returncode,
            0,
        )
        self.assertEqual(self.fixture.store.active_review_findings("review-task"), [])
        attempts = self.fixture.store.list_attempts("review-task")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["head_sha"], first_commit)


if __name__ == "__main__":
    unittest.main()
