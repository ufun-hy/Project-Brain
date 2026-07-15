from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from project_brain.codex import CodexAdapter
from project_brain.errors import TransientTaskError
from project_brain.git_history import GitHistoryNormalizer
from project_brain.worktrees import WorktreeManager, process_alive

from tests.helpers import CoreFixture, create_remote_clone, git


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "codex-adapter")
        script = (
            "import pathlib, subprocess, sys; "
            "prompt=sys.stdin.read(); "
            "pathlib.Path('agent.txt').write_text(prompt); "
            "subprocess.run(['git','add','agent.txt'], check=True); "
            "subprocess.run(['git','commit','-m','agent commit'], check=True)"
        )
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            codex_command=[sys.executable, "-c", script],
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def test_agent_commit_runs_in_task_worktree_and_is_normalized(self) -> None:
        self.fixture.add_task(
            "adapter-task",
            payload={"prompt": "worktree only\n", "commit_message": "canonical"},
        )
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        record = manager.create(task, self.project)
        task = self.fixture.store.get_task("adapter-task")
        normalizer = GitHistoryNormalizer()
        snapshot = normalizer.capture(
            record["path"],
            expected_branch=record["branch"],
            base_sha=record["base_sha"],
        )
        result = CodexAdapter(self.fixture.store, normalizer).execute(
            task=task,
            project=self.project,
            worktree=record["path"],
            snapshot=snapshot,
        )
        self.assertEqual(Path(record["path"], "agent.txt").read_text(), "worktree only\n")
        self.assertFalse((self.repo / "agent.txt").exists())
        self.assertEqual(
            git(Path(record["path"]), "rev-list", "--count", f"{record['base_sha']}..HEAD").stdout.strip(),
            "1",
        )
        self.assertEqual(result.commit, git(Path(record["path"]), "rev-parse", "HEAD").stdout.strip())
        session_id = self.fixture.store.get_task("adapter-task")["agent_session_id"]
        self.assertTrue(session_id)
        session = self.fixture.store.get_agent_session(session_id)
        self.assertEqual(session["status"], "completed")
        self.assertIsNotNone(session["child_pid"])
        self.assertIsNotNone(session["child_pgid"])
        self.assertIsNotNone(session["heartbeat_at"])

    def test_long_running_session_refreshes_agent_and_worktree_heartbeats(self) -> None:
        project = dict(self.project)
        project["codex_command"] = [
            sys.executable,
            "-c",
            "import pathlib,time; time.sleep(0.35); pathlib.Path('heartbeat.txt').write_text('ok')",
        ]
        self.fixture.store.register_project(project)
        self.fixture.add_task("heartbeat-task", payload={"prompt": "wait"})
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        record = manager.create(task, project)
        initial_heartbeat = record["heartbeat_at"]
        snapshot = GitHistoryNormalizer().capture(
            record["path"], expected_branch=record["branch"], base_sha=record["base_sha"]
        )

        CodexAdapter(
            self.fixture.store,
            heartbeat_interval_seconds=0.05,
        ).execute(
            task=self.fixture.store.get_task("heartbeat-task"),
            project=project,
            worktree=record["path"],
            snapshot=snapshot,
        )

        session_id = self.fixture.store.get_task("heartbeat-task")["agent_session_id"]
        session = self.fixture.store.get_agent_session(session_id)
        worktree = self.fixture.store.get_worktree("heartbeat-task")
        self.assertGreater(session["heartbeat_at"], session["started_at"])
        self.assertGreater(worktree["heartbeat_at"], initial_heartbeat)

    def test_timeout_terminates_the_entire_codex_process_group(self) -> None:
        grandchild_pid_file = self.fixture.root / "grandchild.pid"
        script = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            f"pathlib.Path({str(grandchild_pid_file)!r}).write_text(str(child.pid)); "
            "time.sleep(60)"
        )
        project = dict(self.project)
        project["codex_command"] = [sys.executable, "-c", script]
        self.fixture.store.register_project(project)
        self.fixture.add_task(
            "timeout-task",
            payload={"prompt": "timeout", "timeout_seconds": 1},
        )
        task = self.fixture.store.claim_next()
        manager = WorktreeManager(self.fixture.store, self.fixture.runtime)
        record = manager.create(task, project)
        snapshot = GitHistoryNormalizer().capture(
            record["path"], expected_branch=record["branch"], base_sha=record["base_sha"]
        )

        with self.assertRaises(TransientTaskError):
            CodexAdapter(
                self.fixture.store,
                heartbeat_interval_seconds=0.05,
                termination_grace_seconds=0.1,
            ).execute(
                task=self.fixture.store.get_task("timeout-task"),
                project=project,
                worktree=record["path"],
                snapshot=snapshot,
            )

        self.assertTrue(grandchild_pid_file.exists())
        grandchild_pid = int(grandchild_pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process_alive(grandchild_pid):
            time.sleep(0.05)
        self.assertFalse(process_alive(grandchild_pid))
        session_id = self.fixture.store.get_task("timeout-task")["agent_session_id"]
        self.assertEqual(self.fixture.store.get_agent_session(session_id)["status"], "timed_out")


if __name__ == "__main__":
    unittest.main()
