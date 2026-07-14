from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.codex import CodexAdapter
from project_brain.git_history import GitHistoryNormalizer
from project_brain.worktrees import WorktreeManager

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
        manager = WorktreeManager(self.fixture.store)
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
        self.assertTrue(self.fixture.store.get_task("adapter-task")["agent_session_id"])


if __name__ == "__main__":
    unittest.main()
