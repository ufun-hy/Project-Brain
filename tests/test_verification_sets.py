from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.models import AttemptPhase, TaskStatus
from project_brain.verification import VerificationRunner
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone


class VerificationSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "verification-sets")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            verification_commands=[
                {
                    "id": "stable-check",
                    "text": "Stable evidence",
                    "command": [sys.executable, "-c", "print('stable output')"],
                    "always_run": True,
                }
            ],
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def test_two_verification_rounds_keep_immutable_attempt_scoped_artifacts(self) -> None:
        self.fixture.add_task("two-rounds", task_type="write_files")
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        runner = VerificationRunner(self.fixture.store, self.fixture.runtime)

        first_task = self.fixture.store.claim_next()
        record = manager.create(first_task, self.project)
        first_task = self.fixture.store.set_task_fields(
            "two-rounds", commit=record["base_sha"], head_sha=record["base_sha"]
        )
        first_task = self.fixture.store.set_attempt_phase(
            "two-rounds", AttemptPhase.VERIFICATION
        )
        first_set = self.fixture.store.create_verification_set(
            "two-rounds", canonical_head_sha=record["base_sha"]
        )
        first_results = runner.run(
            task=first_task,
            project=self.project,
            worktree=record["path"],
            verification_set=first_set,
        )
        self.fixture.store.finalize_verification_set(
            first_set["verification_set_id"], status="completed"
        )
        first_artifact = Path(first_results[0]["artifact_path"])
        first_bytes = first_artifact.read_bytes()
        self.assertIn("attempt-0001", str(first_artifact))
        self.assertIn(
            f"verification-set-{first_set['verification_set_id']:06d}",
            str(first_artifact),
        )

        self.fixture.store.transition("two-rounds", TaskStatus.AWAITING_REVIEW)
        self.fixture.store.finish_attempt("two-rounds", status="completed")
        self.fixture.store.transition("two-rounds", TaskStatus.NEEDS_CHANGES)
        second_task = self.fixture.store.claim_next()
        second_task = self.fixture.store.set_attempt_phase(
            "two-rounds", AttemptPhase.VERIFICATION
        )
        second_set = self.fixture.store.create_verification_set(
            "two-rounds", canonical_head_sha=record["base_sha"]
        )
        second_results = runner.run(
            task=second_task,
            project=self.project,
            worktree=record["path"],
            verification_set=second_set,
        )
        second_artifact = Path(second_results[0]["artifact_path"])

        self.assertNotEqual(first_artifact, second_artifact)
        self.assertIn("attempt-0002", str(second_artifact))
        self.assertEqual(first_artifact.read_bytes(), first_bytes)
        self.assertEqual(first_artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(second_artifact.stat().st_mode & 0o777, 0o600)
        persisted_first = self.fixture.store.list_verifications(
            "two-rounds", verification_set_id=first_set["verification_set_id"]
        )
        persisted_second = self.fixture.store.list_verifications(
            "two-rounds", verification_set_id=second_set["verification_set_id"]
        )
        self.assertEqual(Path(persisted_first[0]["artifact_path"]).read_bytes(), first_bytes)
        self.assertEqual(
            Path(persisted_second[0]["artifact_path"]).read_bytes(),
            second_artifact.read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
