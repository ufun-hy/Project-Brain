from __future__ import annotations

import sys
import sqlite3
import unittest
from pathlib import Path

from project_brain.engine import TaskEngine
from project_brain.errors import InvalidTaskError, StateTransitionError
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
        applied = self.fixture.store.apply_review_verdict(
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
        review = applied["review"]
        changed = applied["task"]
        self.assertEqual(changed["attempt_phase"], AttemptPhase.IMPLEMENTATION.value)
        self.assertEqual(review["head_sha"], first_commit)

        active = self.fixture.store.get_project("project-one")
        active["codex_command"] = [sys.executable, "-c", "raise SystemExit(97)"]
        self.fixture.store.register_project(active)
        self.assertGreater(
            self.fixture.store.get_project("project-one")["config_revision"],
            changed["project_config_revision"],
        )

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

    def test_review_verdict_rejects_invalid_state_without_side_effects(self) -> None:
        self.fixture.add_task("invalid-state")
        self.fixture.store.set_task_fields(
            "invalid-state", commit="a" * 40, head_sha="a" * 40
        )
        with self.assertRaises(StateTransitionError):
            self.fixture.store.apply_review_verdict(
                "invalid-state",
                verdict="approved",
                head_sha="a" * 40,
                findings=[],
            )
        self.assertEqual(self.fixture.store.list_reviews("invalid-state"), [])
        self.assertEqual(
            self.fixture.store.get_task("invalid-state")["status"],
            TaskStatus.PENDING.value,
        )

    def test_review_verdict_validates_head_and_finding_policy_before_writing(self) -> None:
        self.fixture.add_task(
            "validation",
            payload={"prompt": "validate", "commit_message": "canonical"},
        )
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        head = result["task"]["commit"]
        cases = [
            {
                "verdict": "needs_changes",
                "head_sha": head,
                "findings": [],
            },
            {
                "verdict": "approved",
                "head_sha": "b" * 40,
                "findings": [],
            },
            {
                "verdict": "approved",
                "head_sha": head,
                "findings": [
                    {
                        "severity": "blocker",
                        "evidence": "Blocking defect remains",
                        "requirement": "Resolve the blocker",
                    }
                ],
            },
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(InvalidTaskError):
                    self.fixture.store.apply_review_verdict("validation", **case)
                self.assertEqual(self.fixture.store.list_reviews("validation"), [])
                self.assertEqual(
                    self.fixture.store.get_task("validation")["status"],
                    TaskStatus.AWAITING_REVIEW.value,
                )
        applied = self.fixture.store.apply_review_verdict(
            "validation",
            verdict="approved",
            head_sha=head,
            findings=[
                {
                    "severity": "minor",
                    "evidence": "Optional cleanup remains",
                    "requirement": "Consider a later cleanup",
                }
            ],
        )
        self.assertEqual(applied["task"]["status"], TaskStatus.READY_TO_MERGE.value)

    def test_verification_failed_accepts_only_needs_changes(self) -> None:
        self.fixture.add_task("verification-review")
        self.fixture.store.claim_next()
        self.fixture.store.set_task_fields(
            "verification-review", commit="c" * 40, head_sha="c" * 40
        )
        self.fixture.store.transition(
            "verification-review", TaskStatus.VERIFICATION_FAILED
        )
        with self.assertRaises(StateTransitionError):
            self.fixture.store.apply_review_verdict(
                "verification-review",
                verdict="approved",
                head_sha="c" * 40,
                findings=[],
            )
        applied = self.fixture.store.apply_review_verdict(
            "verification-review",
            verdict="needs_changes",
            head_sha="c" * 40,
            findings=[
                {
                    "severity": "major",
                    "evidence": "Verification command failed",
                    "requirement": "Repair the failed verification",
                }
            ],
        )
        self.assertEqual(applied["task"]["status"], TaskStatus.NEEDS_CHANGES.value)

    def test_database_failure_rolls_back_review_findings_transition_and_event(self) -> None:
        self.fixture.add_task(
            "rollback-review",
            payload={"prompt": "rollback", "commit_message": "canonical"},
        )
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        head = result["task"]["commit"]
        events_before = self.fixture.store.list_events("rollback-review")
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_review_transition
                BEFORE UPDATE OF status ON tasks
                WHEN NEW.task_id = 'rollback-review'
                BEGIN
                    SELECT RAISE(ABORT, 'simulated transition failure');
                END
                """
            )
        with self.assertRaises(sqlite3.DatabaseError):
            self.fixture.store.apply_review_verdict(
                "rollback-review",
                verdict="approved",
                head_sha=head,
                findings=[],
            )
        self.assertEqual(self.fixture.store.list_reviews("rollback-review"), [])
        self.assertEqual(
            self.fixture.store.get_task("rollback-review")["status"],
            TaskStatus.AWAITING_REVIEW.value,
        )
        self.assertEqual(
            self.fixture.store.list_events("rollback-review"), events_before
        )


if __name__ == "__main__":
    unittest.main()
