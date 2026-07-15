from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.errors import StateTransitionError
from project_brain.models import CanonicalTask, TaskStatus
from project_brain.store import SCHEMA_VERSION, TaskStore
from project_brain.runtime import RuntimePaths

from tests.helpers import CoreFixture


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_schema_initialization_is_repeatable_and_persistent(self) -> None:
        self.fixture.store.initialize()
        reopened = TaskStore(self.fixture.runtime.database)
        reopened.initialize()
        self.assertEqual(reopened.schema_version(), SCHEMA_VERSION)
        self.assertEqual(reopened.list_projects()[0]["project_id"], "project-one")

    def test_task_id_is_idempotent(self) -> None:
        task = CanonicalTask(
            task_id="same",
            project_id="project-one",
            dedupe_key="flow",
            revision=1,
            source_type="test",
            goal="first",
            payload={"prompt": "test"},
        )
        first, created = self.fixture.store.insert_task(task)
        second, created_again = self.fixture.store.insert_task(task)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(len(self.fixture.store.list_tasks()), 1)

    def test_same_dedupe_revision_is_logically_idempotent(self) -> None:
        self.fixture.add_task("first", dedupe_key="flow")
        duplicate, created = self.fixture.store.insert_task(
            CanonicalTask(
                task_id="different-id",
                project_id="project-one",
                dedupe_key="flow",
                revision=1,
                source_type="test",
                goal="duplicate",
                payload={"prompt": "test"},
            )
        )
        self.assertFalse(created)
        self.assertEqual(duplicate["task_id"], "first")

    def test_new_revision_supersedes_named_old_task(self) -> None:
        self.fixture.add_task("old", dedupe_key="flow", revision=1)
        new, created = self.fixture.store.insert_task(
            CanonicalTask(
                task_id="new",
                project_id="project-one",
                dedupe_key="flow",
                revision=2,
                source_type="test",
                goal="revision two",
                supersedes="old",
                payload={"prompt": "test"},
            )
        )
        self.assertTrue(created)
        self.assertEqual(new["status"], TaskStatus.PENDING.value)
        self.assertEqual(self.fixture.store.get_task("old")["status"], TaskStatus.SUPERSEDED.value)
        events = self.fixture.store.list_events("old")
        self.assertEqual(events[-1]["event_type"], "task_superseded")

    def test_claim_is_transactional_and_claims_one_task(self) -> None:
        self.fixture.add_task("one")
        self.fixture.add_task("two")
        first = self.fixture.store.claim_next()
        self.assertIsNotNone(first)
        assert first
        self.assertEqual(first["status"], TaskStatus.RUNNING.value)
        running = [task for task in self.fixture.store.list_tasks() if task["status"] == "running"]
        self.assertEqual(len(running), 1)
        self.assertEqual(self.fixture.store.list_attempts(first["task_id"])[0]["status"], "running")

    def test_concurrent_claimers_cannot_claim_the_same_task(self) -> None:
        self.fixture.add_task("only")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.fixture.store.claim_next(), range(2)))
        claimed = [result for result in results if result is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["task_id"], "only")
        self.assertEqual(self.fixture.store.get_task("only")["attempt_count"], 1)

    def test_unexpired_running_task_is_not_claimed_twice(self) -> None:
        self.fixture.add_task("one")
        first = self.fixture.store.claim_next()
        self.assertEqual(first["task_id"], "one")
        self.assertIsNone(self.fixture.store.claim_next())
        self.assertEqual(self.fixture.store.get_task("one")["attempt_count"], 1)

    def test_expired_task_is_marked_and_not_claimed(self) -> None:
        expiry = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.fixture.add_task("expired", expires_at=expiry)
        self.assertIsNone(self.fixture.store.claim_next())
        self.assertEqual(self.fixture.store.get_task("expired")["status"], TaskStatus.EXPIRED.value)

    def test_expired_running_task_is_not_reclaimed(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.fixture.add_task("running-expiry", expires_at=future)
        self.fixture.store.claim_next()
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE tasks SET expires_at = ? WHERE task_id = 'running-expiry'", (past,)
            )
        self.assertIsNone(self.fixture.store.claim_next())
        self.assertEqual(
            self.fixture.store.get_task("running-expiry")["status"], TaskStatus.EXPIRED.value
        )

    def test_accepted_superseded_and_expired_tasks_never_execute(self) -> None:
        self.fixture.add_task("accepted")
        self.fixture.store.claim_next()
        self.fixture.store.transition("accepted", TaskStatus.AWAITING_REVIEW)
        self.fixture.store.transition("accepted", TaskStatus.READY_TO_MERGE)
        self.fixture.store.transition("accepted", TaskStatus.MERGING)
        self.fixture.store.transition("accepted", TaskStatus.ACCEPTED)
        self.fixture.add_task("superseded")
        self.fixture.store.transition("superseded", TaskStatus.SUPERSEDED)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.fixture.add_task("expired", expires_at=past)
        self.assertIsNone(self.fixture.store.claim_next())

    def test_invalid_transition_is_rejected(self) -> None:
        self.fixture.add_task("task")
        with self.assertRaises(StateTransitionError):
            self.fixture.store.transition("task", TaskStatus.ACCEPTED)

    def test_needs_changes_can_be_claimed_as_a_new_attempt(self) -> None:
        self.fixture.add_task("review-cycle")
        self.fixture.store.claim_next()
        self.fixture.store.transition("review-cycle", TaskStatus.AWAITING_REVIEW)
        self.fixture.store.transition("review-cycle", TaskStatus.NEEDS_CHANGES)
        claimed = self.fixture.store.claim_next()
        self.assertEqual(claimed["task_id"], "review-cycle")
        self.assertEqual(claimed["attempt_count"], 2)

    def test_status_events_are_append_only(self) -> None:
        self.fixture.add_task("audit")
        self.fixture.store.claim_next()
        self.fixture.store.transition("audit", TaskStatus.AWAITING_REVIEW)
        events = self.fixture.store.list_events("audit")
        self.assertEqual(
            [event["event_type"] for event in events],
            ["task_created", "task_claimed", "status_changed"],
        )

    def test_process_state_can_be_read_after_reopen(self) -> None:
        self.fixture.add_task("interrupted")
        self.fixture.store.claim_next()
        reopened = TaskStore(self.fixture.runtime.database)
        reopened.initialize()
        task = reopened.get_task("interrupted")
        self.assertEqual(task["status"], TaskStatus.RUNNING.value)
        self.assertEqual(reopened.list_events("interrupted")[-1]["event_type"], "task_claimed")


class IsolatedRuntimeTests(unittest.TestCase):
    def test_test_database_can_live_under_explicit_temp_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "isolated" / "brain.db"
            store = TaskStore(database)
            store.initialize()
            self.assertTrue(database.exists())
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)

    def test_runtime_root_environment_override_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "override"
            with patch.dict("os.environ", {"PROJECT_BRAIN_RUNTIME_ROOT": str(root)}):
                runtime = RuntimePaths.from_value().ensure()
            self.assertEqual(runtime.root, root.resolve())
            self.assertTrue(runtime.worktrees_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
