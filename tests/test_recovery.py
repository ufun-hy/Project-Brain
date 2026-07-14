from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from project_brain.models import AttemptPhase, TaskStatus
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
