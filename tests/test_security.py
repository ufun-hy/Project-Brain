from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.errors import InvalidTaskError
from project_brain.security import redact_text
from project_brain.verification import VerificationRunner

from tests.helpers import CoreFixture


class SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_known_secret_in_task_is_rejected_before_database_write(self) -> None:
        token = "Authorization: Bearer " + "".join(map(chr, range(97, 123)))
        with self.assertRaises(InvalidTaskError):
            self.fixture.add_task(
                "secret-task",
                payload={"prompt": token},
            )
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_verification_output_is_redacted_in_artifact_and_database(self) -> None:
        task = self.fixture.add_task(
            "redaction",
            acceptance_criteria=[
                {
                    "id": "redact",
                    "text": "Output is captured safely",
                    "command": [
                        sys.executable,
                        "-c",
                        "print('api_' + 'key=' + ''.join(map(chr, range(97, 119))))",
                    ],
                }
            ],
        )
        worktree = self.fixture.root / "verification-worktree"
        worktree.mkdir()
        results = VerificationRunner(self.fixture.store, self.fixture.runtime).run(
            task=task,
            project=self.fixture.store.get_project("project-one"),
            worktree=worktree,
        )
        artifact = Path(results[0]["artifact_path"]).read_text(encoding="utf-8")
        persisted = self.fixture.store.list_verifications("redaction")[0]
        self.assertIn("[REDACTED]", artifact)
        self.assertNotIn("abcdefghijklmnopqrstuv", artifact)
        self.assertNotIn("abcdefghijklmnopqrstuv", persisted["evidence_summary"])
        self.assertNotIn(
            b"abcdefghijklmnopqrstuv", self.fixture.runtime.database.read_bytes()
        )

    def test_common_token_formats_are_redacted(self) -> None:
        token = "github_" + "pat_" + "".join(map(chr, range(97, 123))) + "123456"
        value = redact_text("token " + token)
        self.assertNotIn("github_pat_", value)
        self.assertIn("[REDACTED]", value)


if __name__ == "__main__":
    unittest.main()
