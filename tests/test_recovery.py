from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from project_brain.forensics import TerminalWorktreeReconciler
from project_brain.models import AttemptPhase, TaskStatus
from project_brain.process_supervision import capture_process_identity, terminate_process_group
from project_brain.recovery import RecoveryManager
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone, git, pythonpath_env


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "recovery")
        self.source_root = Path(__file__).resolve().parents[1] / "src"

    def tearDown(self) -> None:
        self.fixture.close()

    def _starting_session_without_pid(self, task_id: str) -> tuple[WorktreeManager, str]:
        project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=False,
            auto_pr=False,
        )
        self.fixture.add_task(task_id)
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        manager.create(task, project)
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = ?",
                (task_id,),
            )
        session_id = str(uuid.uuid4())
        self.fixture.store.record_agent_session(
            session_id=session_id,
            task_id=task_id,
            adapter="codex",
            command=["codex", "exec"],
        )
        return manager, session_id

    def test_recovery_dry_run_does_not_change_state(self) -> None:
        self.fixture.add_project(
            repo_path=str(self.repo), remote_url=str(self.remote), auto_push=False, auto_pr=False
        )
        self.fixture.add_task("dry-run")
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        manager.create(task, self.fixture.store.get_project("project-one"))
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = 'dry-run'"
            )
        actions = RecoveryManager(self.fixture.store, manager).reconcile(
            "dry-run", execute=False
        )
        self.assertEqual(actions[0]["action"], "would_recover")
        self.assertEqual(self.fixture.store.get_task("dry-run")["status"], "running")

    def test_missing_pid_remains_running_during_startup_grace(self) -> None:
        manager, session_id = self._starting_session_without_pid("startup-grace")
        action = RecoveryManager(
            self.fixture.store,
            manager,
            ambiguous_startup_grace_seconds=300,
        ).reconcile("startup-grace", execute=True)[0]
        self.assertEqual(action["action"], "unchanged")
        self.assertEqual(
            self.fixture.store.get_task("startup-grace")["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertEqual(
            self.fixture.store.get_agent_session(session_id)["status"], "starting"
        )

    def test_missing_pid_becomes_recovery_blocked_then_operator_confirms_retry(self) -> None:
        manager, session_id = self._starting_session_without_pid("startup-blocked")
        recovery = RecoveryManager(
            self.fixture.store,
            manager,
            ambiguous_startup_grace_seconds=0,
        )
        blocked = recovery.reconcile("startup-blocked", execute=True)[0]
        self.assertEqual(blocked["action"], "recovery_blocked")
        self.assertEqual(blocked["to_status"], TaskStatus.RECOVERY_BLOCKED.value)
        self.assertEqual(
            self.fixture.store.get_task("startup-blocked")["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        self.assertEqual(
            self.fixture.store.get_agent_session(session_id)["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        self.assertEqual(
            self.fixture.store.list_attempts("startup-blocked")[0]["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        self.assertIsNone(self.fixture.store.claim_next())

        resolved = recovery.reconcile(
            "startup-blocked", execute=True, confirm_no_agent=True
        )[0]
        self.assertEqual(resolved["action"], "recovery_resolved")
        self.assertEqual(resolved["to_status"], TaskStatus.RETRY_PENDING.value)
        self.assertEqual(
            self.fixture.store.get_task("startup-blocked")["status"],
            TaskStatus.RETRY_PENDING.value,
        )
        self.assertEqual(
            self.fixture.store.get_agent_session(session_id)["status"],
            "confirmed_no_agent",
        )
        event_types = [
            item["event_type"]
            for item in self.fixture.store.list_events("startup-blocked")
        ]
        self.assertIn("task_recovery_blocked", event_types)
        self.assertIn("task_recovery_resolved", event_types)

    def test_operator_can_cancel_recovery_blocked_task(self) -> None:
        manager, _ = self._starting_session_without_pid("startup-cancelled")
        recovery = RecoveryManager(
            self.fixture.store,
            manager,
            ambiguous_startup_grace_seconds=0,
        )
        recovery.reconcile("startup-cancelled", execute=True)
        cancelled = recovery.reconcile(
            "startup-cancelled", execute=True, cancel=True
        )[0]
        self.assertEqual(cancelled["to_status"], TaskStatus.FAILED.value)
        self.assertEqual(
            self.fixture.store.get_task("startup-cancelled")["status"],
            TaskStatus.FAILED.value,
        )

    def test_operator_can_resume_recovery_blocked_task_after_inspection(self) -> None:
        manager, session_id = self._starting_session_without_pid("startup-resumed")
        recovery = RecoveryManager(
            self.fixture.store,
            manager,
            ambiguous_startup_grace_seconds=0,
        )
        recovery.reconcile("startup-resumed", execute=True)
        resumed = recovery.reconcile(
            "startup-resumed", execute=True, resume=True
        )[0]
        self.assertEqual(resumed["resolution"], "resume")
        self.assertEqual(resumed["to_status"], TaskStatus.RETRY_PENDING.value)
        self.assertEqual(
            self.fixture.store.get_agent_session(session_id)["status"],
            "operator_resumed",
        )

    def test_identity_mismatch_blocks_recovery_without_signalling_process(self) -> None:
        project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=False,
            auto_pr=False,
        )
        self.fixture.add_task("identity-mismatch")
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        manager.create(task, project)
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
            text=True,
        )
        identity = capture_process_identity(child.pid, child.pid)
        self.assertIsNotNone(identity)
        wrong_identity = {**identity, "start_marker": f"{identity['start_marker']}-reused"}
        session_id = str(uuid.uuid4())
        self.fixture.store.record_agent_session(
            session_id=session_id,
            task_id="identity-mismatch",
            adapter="codex",
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
        )
        self.fixture.store.start_agent_session(
            session_id,
            child_pid=child.pid,
            child_pgid=child.pid,
            child_identity=wrong_identity,
        )
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = 'identity-mismatch'"
            )
        try:
            blocked = RecoveryManager(
                self.fixture.store,
                manager,
                termination_grace_seconds=0.1,
            ).reconcile(
                "identity-mismatch", execute=True, terminate_agent=True
            )[0]
            self.assertEqual(blocked["to_status"], TaskStatus.RECOVERY_BLOCKED.value)
            self.assertIn("identity", blocked["reason"])
            self.assertIsNone(child.poll())
            RecoveryManager(self.fixture.store, manager).reconcile(
                "identity-mismatch", execute=True, cancel=True
            )
            cleanup = TerminalWorktreeReconciler(
                self.fixture.store, self.fixture.runtime, manager
            ).reconcile(execute=True)[0]
            self.assertEqual(cleanup["action"], "retained")
            self.assertIn("process group prevents cleanup", cleanup["reason"])
            self.assertTrue(
                Path(
                    self.fixture.store.get_worktree("identity-mismatch")["path"]
                ).exists()
            )
        finally:
            terminate_process_group(
                child_pid=child.pid,
                child_pgid=child.pid,
                expected_identity=identity,
                grace_seconds=0.1,
                process=child,
            )

    def test_real_process_interruption_is_reconciled_and_retried(self) -> None:
        child_pid_file = self.fixture.root / "codex-child.pid"
        blocking = (
            "import os,pathlib,time; "
            f"pathlib.Path({str(child_pid_file)!r}).write_text(str(os.getpid())); "
            "time.sleep(1.5)"
        )
        self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            codex_command=[sys.executable, "-c", blocking],
            auto_push=False,
            auto_pr=False,
        )
        self.fixture.add_task("interrupted", payload={"prompt": "block until killed"})
        command = [
            sys.executable,
            "-m",
            "project_brain",
            "--runtime-root",
            str(self.fixture.runtime.root),
            "apply",
            "--json",
        ]
        process = subprocess.Popen(
            command,
            cwd=str(self.fixture.root),
            env=pythonpath_env(self.source_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = self.fixture.store.get_task("interrupted")
            if task.get("agent_session_id") and child_pid_file.exists():
                break
            time.sleep(0.05)
        else:
            process.kill()
            self.fail("subprocess never entered the Codex agent session")
        process.terminate()
        process.communicate(timeout=5)
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        session_id = self.fixture.store.get_task("interrupted")["agent_session_id"]
        session = self.fixture.store.get_agent_session(session_id)
        self.assertEqual(session["child_pid"], child_pid)
        self.assertEqual(session["child_pgid"], child_pid)
        self.assertEqual(session["child_identity"]["pid"], child_pid)

        # The Codex child owns an independent process group and survives the
        # Bridge parent. Startup recovery must not claim a second attempt while
        # that persisted child is still alive.
        immediate = subprocess.run(
            command,
            cwd=str(self.fixture.root),
            env=pythonpath_env(self.source_root),
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(immediate.returncode, 0, immediate.stderr)
        self.assertEqual(json.loads(immediate.stdout)["status"], "idle")
        still_running = self.fixture.store.get_task("interrupted")
        self.assertEqual(still_running["status"], TaskStatus.RUNNING.value)
        self.assertEqual(still_running["attempt_count"], 1)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("orphaned Codex child did not exit naturally")

        recovered = subprocess.run(
            [
                sys.executable,
                "-m",
                "project_brain",
                "--runtime-root",
                str(self.fixture.runtime.root),
                "tasks",
                "recover",
                "interrupted",
                "--execute",
                "--json",
            ],
            cwd=str(self.fixture.root),
            env=pythonpath_env(self.source_root),
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(
            json.loads(recovered.stdout)["actions"][0]["to_status"],
            TaskStatus.RETRY_PENDING.value,
        )

        project = self.fixture.store.get_project("project-one")
        project["codex_command"] = [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('recovered.txt').write_text('ok\\n')",
        ]
        self.fixture.store.register_project(project)
        completed = subprocess.run(
            command,
            cwd=str(self.fixture.root),
            env=pythonpath_env(self.source_root),
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout)["status"], TaskStatus.AWAITING_REVIEW.value
        )
        attempts = self.fixture.store.list_attempts("interrupted")
        self.assertEqual([item["status"] for item in attempts], ["interrupted", "completed"])
        final_worktree = Path(self.fixture.store.get_task("interrupted")["worktree_path"])
        base_sha = self.fixture.store.get_worktree("interrupted")["base_sha"]
        self.assertEqual(
            git(
                final_worktree,
                "rev-list",
                "--count",
                f"{base_sha}..HEAD",
            ).stdout.strip(),
            "1",
        )

    def test_interrupted_review_with_released_worktree_restores_awaiting_review(self) -> None:
        project = self.fixture.add_project(
            repo_path=str(self.repo), remote_url=str(self.remote), auto_push=True, auto_pr=False
        )
        self.fixture.add_task("review-recovery")
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        record = manager.create(task, project)
        worktree = Path(record["path"])
        (worktree / "result.txt").write_text("done\n", encoding="utf-8")
        git(worktree, "add", ".")
        git(worktree, "commit", "-m", "canonical")
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        git(worktree, "push", "-u", "origin", record["branch"])
        self.fixture.store.set_task_fields("review-recovery", head_sha=head, commit=head)
        self.fixture.store.set_attempt_phase("review-recovery", AttemptPhase.REVIEW)
        git(self.repo, "worktree", "remove", str(worktree))
        git(self.repo, "worktree", "prune")
        git(self.repo, "branch", "-D", record["branch"])
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE worktrees SET owner_pid = 99999999 WHERE task_id = 'review-recovery'"
            )
        action = RecoveryManager(self.fixture.store, manager).reconcile(
            "review-recovery", execute=True
        )[0]
        self.assertEqual(action["to_status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertEqual(
            self.fixture.store.get_task("review-recovery")["status"],
            TaskStatus.AWAITING_REVIEW.value,
        )


if __name__ == "__main__":
    unittest.main()
