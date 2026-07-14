from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from project_brain.engine import TaskEngine
from project_brain.errors import FetchError, TransientTaskError
from tests.helpers import git
from project_brain.models import TaskStatus

from tests.helpers import CoreFixture, create_remote_clone


class TaskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "engine")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def _write_task(self, task_id: str, **overrides):
        payload = {
            "files": [{"path": f"{task_id}.txt", "content": "done\n"}],
            "commit_message": f"feat: {task_id}",
        }
        payload.update(overrides.pop("payload", {}))
        return self.fixture.add_task(
            task_id,
            task_type="write_files",
            payload=payload,
            **overrides,
        )

    def test_process_executes_at_most_one_pending_task(self) -> None:
        self._write_task("one")
        self._write_task("two")
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.AWAITING_REVIEW.value)
        statuses = {task["task_id"]: task["status"] for task in self.fixture.store.list_tasks()}
        self.assertEqual(list(statuses.values()).count(TaskStatus.AWAITING_REVIEW.value), 1)
        self.assertEqual(list(statuses.values()).count(TaskStatus.PENDING.value), 1)

    def test_success_stops_at_awaiting_review_and_retains_worktree(self) -> None:
        self._write_task("success")
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        task = result["task"]
        self.assertEqual(task["status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertNotEqual(task["status"], TaskStatus.ACCEPTED.value)
        self.assertTrue(Path(task["worktree_path"]).exists())
        self.assertTrue(task["commit"])

    def test_permanent_no_changes_error_is_not_retried(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["allowed_commands"] = {"noop": [sys.executable, "-c", "pass"]}
        self.fixture.store.register_project(project)
        self.fixture.add_task(
            "noop",
            task_type="command",
            payload={"command": "noop", "commit_message": "noop"},
        )
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.FAILED.value)
        self.assertEqual(result["task"]["attempt_count"], 1)
        self.assertIn("no file or commit changes", result["task"]["last_error"])
        self.assertEqual(self.fixture.store.get_worktree("noop")["status"], "active")
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = 'noop'"
            )

        # The next startup first persists immutable failure evidence, then
        # safely removes the terminal worktree before looking for new work.
        idle = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(idle["status"], "idle")
        archive = self.fixture.store.get_forensic_archive("noop")
        self.assertIsNotNone(archive)
        self.assertTrue(Path(archive["artifact_path"], "manifest.json").is_file())
        self.assertFalse(Path(result["task"]["worktree_path"]).exists())
        self.assertEqual(self.fixture.store.get_worktree("noop")["status"], "cleaned")

    def test_transient_error_retries_only_until_policy_limit(self) -> None:
        self._write_task("transient")
        worktrees = Mock()
        worktrees.create.side_effect = FetchError("offline")
        engine = TaskEngine(
            self.fixture.store,
            self.fixture.runtime,
            max_transient_attempts=2,
            worktrees=worktrees,
        )
        first = engine.apply_once()
        self.assertEqual(first["status"], TaskStatus.RETRY_PENDING.value)
        second = engine.apply_once()
        self.assertEqual(second["status"], TaskStatus.FAILED.value)
        self.assertEqual(second["task"]["attempt_count"], 2)
        self.assertEqual(worktrees.create.call_count, 2)

    def test_each_criterion_has_independent_evidence(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "file-check",
                "text": "Task file exists",
                "command": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; raise SystemExit(not Path('evidence.txt').exists())",
                ],
                "always_run": False,
            }
        ]
        self.fixture.store.register_project(project)
        self._write_task(
            "evidence",
            acceptance_criteria=[
                {
                    "id": "file-exists",
                    "text": "Task file exists",
                    "verification_id": "file-check",
                },
                "Requires human product review",
            ],
        )
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.AWAITING_REVIEW.value)
        evidence = self.fixture.store.list_verifications("evidence")
        self.assertEqual([item["status"] for item in evidence], ["passed", "not_verified"])
        self.assertEqual(evidence[0]["criterion_id"], "file-exists")
        self.assertIsNotNone(evidence[0]["artifact_path"])

    def test_failed_verification_enters_verification_failed_and_retains_worktree(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "deliberate-check",
                "text": "Deliberate failure",
                "command": [sys.executable, "-c", "raise SystemExit(7)"],
                "always_run": False,
            }
        ]
        self.fixture.store.register_project(project)
        self._write_task(
            "bad-check",
            acceptance_criteria=[
                {
                    "id": "deliberate-failure",
                    "text": "Deliberate failure",
                    "verification_id": "deliberate-check",
                }
            ],
        )
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.VERIFICATION_FAILED.value)
        self.assertTrue(Path(result["task"]["worktree_path"]).exists())
        evidence = self.fixture.store.list_verifications("bad-check")
        self.assertEqual(evidence[0]["status"], "failed")
        self.assertEqual(evidence[0]["exit_code"], 7)

    def test_transient_publication_failure_resumes_without_reexecuting_task(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["auto_push"] = True
        project["verification_commands"] = [
            {
                "id": "publication-check",
                "text": "Canonical publication evidence",
                "command": [sys.executable, "-c", "print('canonical evidence')"],
                "always_run": True,
            }
        ]
        self.fixture.store.register_project(project)
        self._write_task("publish-resume")

        class FlakyPublisher:
            def __init__(self):
                self.calls = 0

            def publish(self, **_):
                self.calls += 1
                if self.calls == 1:
                    raise TransientTaskError("temporary GitHub outage")
                return {"pushed": True, "pr_url": "https://example.test/pr/1"}

        publisher = FlakyPublisher()
        engine = TaskEngine(
            self.fixture.store,
            self.fixture.runtime,
            github=publisher,
        )
        first = engine.apply_once()
        self.assertEqual(first["status"], TaskStatus.RETRY_PENDING.value)
        commit = first["task"]["commit"]
        verification_set_id = first["task"]["verification_set_id"]
        first_evidence = self.fixture.store.list_verifications(
            "publish-resume", verification_set_id=verification_set_id
        )
        self.assertEqual(len(first_evidence), 1)
        self.assertEqual(first_evidence[0]["attempt_number"], 1)

        # A different historical head/set must never leak into a publication
        # retry merely because the task's current attempt_count changed.
        with self.fixture.store.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO verification_sets(
                    task_id, canonical_head_sha, source_attempt_number,
                    status, created_at, completed_at
                ) VALUES ('publish-resume', ?, 0, 'completed', '2026-01-01', '2026-01-01')
                """,
                ("b" * 40,),
            )
            historical_set_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO verification_results(
                    task_id, criterion_id, criterion_text, status, evidence_type,
                    evidence_summary, attempt_number, verification_set_id, created_at
                ) VALUES (
                    'publish-resume', 'historical', 'Wrong historical head', 'passed',
                    'trusted_project_command', 'must not publish', 0, ?, '2026-01-01'
                )
                """,
                (historical_set_id,),
            )
        second = engine.apply_once()
        self.assertEqual(second["status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertEqual(second["task"]["commit"], commit)
        self.assertEqual(second["task"]["pr_url"], "https://example.test/pr/1")
        self.assertEqual(publisher.calls, 2)
        self.assertEqual(second["task"]["verification_set_id"], verification_set_id)
        self.assertEqual(
            [item["verification_set_id"] for item in second["evidence"]],
            [verification_set_id],
        )
        attempts = self.fixture.store.list_attempts("publish-resume")
        self.assertEqual(attempts[1]["attempt_number"], 2)
        self.assertEqual(attempts[1]["verification_set_id"], verification_set_id)
        worktree = Path(second["task"]["worktree_path"])
        self.assertEqual(
            git(worktree, "rev-list", "--count", f"{second['task']['base_sha']}..HEAD").stdout.strip(),
            "1",
        )


if __name__ == "__main__":
    unittest.main()
