from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid

from project_brain.engine import TaskEngine
from project_brain.models import TaskStatus
from project_brain.process_supervision import (
    capture_process_identity,
    terminate_process_group,
)
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone


class ClaimGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "claim-gate")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=False,
            auto_pr=False,
        )
        self.manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        self.children: list[tuple[subprocess.Popen[str], dict[str, object]]] = []

    def tearDown(self) -> None:
        for child, identity in self.children:
            if child.poll() is None:
                terminate_process_group(
                    child_pid=child.pid,
                    child_pgid=int(identity["pgid"]),
                    expected_identity=identity,
                    grace_seconds=0.1,
                    process=child,
                )
        self.fixture.close()

    def _running_task_a(self) -> None:
        self.fixture.add_task("task-a", payload={"prompt": "task a"})
        task = self.fixture.store.claim_next()
        self.manager.create(task, self.project)
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = 'task-a'"
            )

    def _pending_task_b(self) -> None:
        self.fixture.add_task(
            "task-b",
            task_type="write_files",
            payload={
                "files": [{"path": "task-b.txt", "content": "must remain pending\n"}],
                "commit_message": "task b",
            },
        )

    def _spawn_agent(self) -> tuple[subprocess.Popen[str], dict[str, object]]:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
            text=True,
        )
        identity = capture_process_identity(child.pid, os.getpgid(child.pid))
        self.assertIsNotNone(identity)
        self.children.append((child, identity))
        return child, identity

    def _record_session(self, identity: dict[str, object]) -> str:
        session_id = str(uuid.uuid4())
        self.fixture.store.record_agent_session(
            session_id=session_id,
            task_id="task-a",
            adapter="codex",
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
        )
        self.fixture.store.start_agent_session(
            session_id,
            child_pid=int(identity["pid"]),
            child_pgid=int(identity["pgid"]),
            child_identity=identity,
        )
        return session_id

    def _assert_task_b_was_not_claimed(self, result: dict[str, object]) -> None:
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["claim_safe"])
        self.assertEqual(result["claim_blockers"][0]["task_id"], "task-a")
        task_b = self.fixture.store.get_task("task-b")
        self.assertEqual(task_b["status"], TaskStatus.PENDING.value)
        self.assertEqual(task_b["attempt_count"], 0)

    def test_missing_pid_inside_startup_grace_blocks_other_claims(self) -> None:
        self._running_task_a()
        self.fixture.store.record_agent_session(
            session_id=str(uuid.uuid4()),
            task_id="task-a",
            adapter="codex",
            command=["codex", "exec"],
        )
        self._pending_task_b()

        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()

        self._assert_task_b_was_not_claimed(result)
        self.assertEqual(
            self.fixture.store.get_task("task-a")["status"], TaskStatus.RUNNING.value
        )

    def test_unverified_live_identity_blocks_other_claims(self) -> None:
        self._running_task_a()
        child, identity = self._spawn_agent()
        wrong_identity = {
            **identity,
            "start_marker": f"{identity['start_marker']}-reused",
        }
        self._record_session(wrong_identity)
        self._pending_task_b()

        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()

        self._assert_task_b_was_not_claimed(result)
        self.assertEqual(
            self.fixture.store.get_task("task-a")["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        self.assertIsNone(child.poll())

    def test_existing_recovery_blocked_live_session_blocks_other_claims(self) -> None:
        self._running_task_a()
        child, identity = self._spawn_agent()
        self._record_session(identity)
        self.fixture.store.block_running_task(
            "task-a", reason="operator resolution required"
        )
        self._pending_task_b()

        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()

        self._assert_task_b_was_not_claimed(result)
        self.assertEqual(
            self.fixture.store.get_task("task-a")["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        self.assertIsNone(child.poll())


if __name__ == "__main__":
    unittest.main()
