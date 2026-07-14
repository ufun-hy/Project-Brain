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
        self._write_task(
            "evidence",
            acceptance_criteria=[
                {
                    "id": "file-exists",
                    "text": "Task file exists",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; raise SystemExit(not Path('evidence.txt').exists())",
                    ],
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
        self._write_task(
            "bad-check",
            acceptance_criteria=[
                {
                    "id": "deliberate-failure",
                    "text": "Deliberate failure",
                    "command": [sys.executable, "-c", "raise SystemExit(7)"],
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
        second = engine.apply_once()
        self.assertEqual(second["status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertEqual(second["task"]["commit"], commit)
        self.assertEqual(second["task"]["pr_url"], "https://example.test/pr/1")
        self.assertEqual(publisher.calls, 2)
        worktree = Path(second["task"]["worktree_path"])
        self.assertEqual(
            git(worktree, "rev-list", "--count", f"{second['task']['base_sha']}..HEAD").stdout.strip(),
            "1",
        )


if __name__ == "__main__":
    unittest.main()
