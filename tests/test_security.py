from __future__ import annotations

import sys
import os
import stat
import unittest
from pathlib import Path

from project_brain.errors import InvalidPathError, InvalidTaskError
from project_brain.locking import RuntimeLock
from project_brain.models import AttemptPhase
from project_brain.security import redact_text
from project_brain.verification import VerificationRunner

from tests.helpers import CoreFixture


class SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project()

    def tearDown(self) -> None:
        self.fixture.close()

    def _verification_context(self, task_id: str):
        task = self.fixture.store.claim_next()
        task = self.fixture.store.set_task_fields(
            task_id, commit="a" * 40, head_sha="a" * 40
        )
        task = self.fixture.store.set_attempt_phase(task_id, AttemptPhase.VERIFICATION)
        verification_set = self.fixture.store.create_verification_set(
            task_id, canonical_head_sha="a" * 40
        )
        return task, verification_set

    def test_known_secret_in_task_is_rejected_before_database_write(self) -> None:
        token = "Authorization: Bearer " + "".join(map(chr, range(97, 123)))
        with self.assertRaises(InvalidTaskError):
            self.fixture.add_task(
                "secret-task",
                payload={"prompt": token},
            )
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_verification_output_is_redacted_in_artifact_and_database(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "redaction-check",
                "text": "Output is captured safely",
                "command": [
                    sys.executable,
                    "-c",
                    "print('api_' + 'key=' + ''.join(map(chr, range(97, 119))))",
                ],
                "always_run": False,
            }
        ]
        self.fixture.store.register_project(project)
        self.fixture.add_task(
            "redaction",
            acceptance_criteria=[
                {
                    "id": "redact",
                    "text": "Output is captured safely",
                    "verification_id": "redaction-check",
                }
            ],
        )
        worktree = self.fixture.root / "verification-worktree"
        worktree.mkdir()
        task, verification_set = self._verification_context("redaction")
        results = VerificationRunner(self.fixture.store, self.fixture.runtime).run(
            task=task,
            project=self.fixture.store.get_project("project-one"),
            worktree=worktree,
            verification_set=verification_set,
        )
        artifact = Path(results[0]["artifact_path"]).read_text(encoding="utf-8")
        persisted = self.fixture.store.list_verifications("redaction")[0]
        self.assertIn("[REDACTED]", artifact)
        self.assertNotIn("abcdefghijklmnopqrstuv", artifact)
        self.assertNotIn("abcdefghijklmnopqrstuv", persisted["evidence_summary"])
        self.assertNotIn(
            b"abcdefghijklmnopqrstuv", self.fixture.runtime.database.read_bytes()
        )
        self.assertEqual(stat.S_IMODE(Path(results[0]["artifact_path"]).stat().st_mode), 0o600)

    def test_runtime_state_permissions_are_private(self) -> None:
        with RuntimeLock(self.fixture.runtime.lock_file):
            pass
        for directory in (
            self.fixture.runtime.root,
            self.fixture.runtime.config_dir,
            self.fixture.runtime.logs_dir,
            self.fixture.runtime.results_dir,
            self.fixture.runtime.worktrees_dir,
        ):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.fixture.runtime.database.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.fixture.runtime.lock_file.stat().st_mode), 0o600)

    def test_result_symlink_escape_is_rejected(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "safe-check",
                "text": "Safe check",
                "command": [sys.executable, "-c", "print('ok')"],
                "always_run": False,
            }
        ]
        self.fixture.store.register_project(project)
        self.fixture.add_task(
            "symlink-result",
            acceptance_criteria=[
                {"id": "safe", "text": "Safe", "verification_id": "safe-check"}
            ],
        )
        outside = self.fixture.root / "outside-results"
        outside.mkdir()
        (self.fixture.runtime.results_dir / "symlink-result").symlink_to(
            outside, target_is_directory=True
        )
        worktree = self.fixture.root / "result-worktree"
        worktree.mkdir()
        task, verification_set = self._verification_context("symlink-result")
        with self.assertRaises(InvalidPathError):
            VerificationRunner(self.fixture.store, self.fixture.runtime).run(
                task=task,
                project=self.fixture.store.get_project("project-one"),
                worktree=worktree,
                verification_set=verification_set,
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_common_token_formats_are_redacted(self) -> None:
        token = "github_" + "pat_" + "".join(map(chr, range(97, 123))) + "123456"
        value = redact_text("token " + token)
        self.assertNotIn("github_pat_", value)
        self.assertIn("[REDACTED]", value)

    def test_email_and_user_home_are_redacted_from_presented_text(self) -> None:
        rendered = redact_text(
            "Contact engineer@example.com at /Users/alice/private-repository"
        )
        self.assertNotIn("engineer@example.com", rendered)
        self.assertNotIn("/Users/alice", rendered)
        self.assertIn("[REDACTED_EMAIL]", rendered)
        self.assertIn("/Users/[REDACTED_USER]/private-repository", rendered)


if __name__ == "__main__":
    unittest.main()
