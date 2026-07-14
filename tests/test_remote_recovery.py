from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.engine import TaskEngine
from project_brain.models import TaskStatus

from tests.helpers import CoreFixture, create_remote_clone, git


class PushingDraftPublisher:
    def __init__(self, pr_url: str) -> None:
        self.pr_url = pr_url
        self.calls: list[str | None] = []

    def publish(self, *, task, worktree, **_):
        self.calls.append(task.get("pr_url"))
        git(Path(worktree), "push", "-u", "origin", task["branch"])
        return {"pushed": True, "pr_url": task.get("pr_url") or self.pr_url}


class RemoteRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "remote-recovery")
        evolve = (
            "from pathlib import Path; p=Path('result.txt'); "
            "p.write_text('second\\n' if p.exists() else 'first\\n')"
        )
        self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            allowed_commands={"evolve": [sys.executable, "-c", evolve]},
            auto_push=True,
            auto_pr=True,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def test_published_task_recovers_from_remote_and_reuses_draft_pr(self) -> None:
        human_file = self.repo / "human-notes.txt"
        human_file.write_text("leave alone\n", encoding="utf-8")
        main_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        main_status = git(self.repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
        self.fixture.add_task(
            "remote-review",
            task_type="command",
            payload={"command": "evolve", "commit_message": "canonical attempt"},
        )
        publisher = PushingDraftPublisher("https://example.test/pr/42")
        engine = TaskEngine(
            self.fixture.store, self.fixture.runtime, github=publisher
        )
        first = engine.apply_once()
        first_commit = first["task"]["commit"]
        first_record = self.fixture.store.get_worktree("remote-review")
        self.assertEqual(first["task"]["status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertEqual(first["worktree_release"]["action"], "released")
        self.assertEqual(first_record["status"], "cleaned")
        self.assertFalse(Path(first_record["path"]).exists())

        self.fixture.store.apply_review_verdict(
            "remote-review",
            verdict="needs_changes",
            head_sha=first_commit,
            findings=[
                {
                    "severity": "major",
                    "file": "result.txt",
                    "evidence": "The first value is incomplete.",
                    "requirement": "Produce the second value.",
                }
            ],
        )
        second = engine.apply_once()
        second_commit = second["task"]["commit"]
        second_record = self.fixture.store.get_worktree("remote-review")
        self.assertEqual(second["task"]["status"], TaskStatus.AWAITING_REVIEW.value)
        self.assertNotEqual(first_commit, second_commit)
        self.assertEqual(second["task"]["pr_url"], "https://example.test/pr/42")
        self.assertEqual(publisher.calls, [None, "https://example.test/pr/42"])
        self.assertEqual(second_record["status"], "cleaned")
        remote_sha = git(
            self.repo, "ls-remote", "--heads", "origin", "brain/remote-review"
        ).stdout.split()[0]
        self.assertEqual(remote_sha, second_commit)
        git(self.repo, "fetch", "origin", "brain/remote-review")
        self.assertEqual(
            git(
                self.repo,
                "merge-base",
                "--is-ancestor",
                first_commit,
                second_commit,
                check=False,
            ).returncode,
            0,
        )
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), main_head)
        self.assertEqual(
            git(self.repo, "status", "--porcelain=v1", "--untracked-files=all").stdout,
            main_status,
        )
        self.assertEqual(human_file.read_text(encoding="utf-8"), "leave alone\n")


if __name__ == "__main__":
    unittest.main()
