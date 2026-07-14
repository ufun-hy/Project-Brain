from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_brain.errors import NoChangesError, TaskHistoryError
from project_brain.git_history import GitHistoryNormalizer

from tests.helpers import git, run


class GitHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        run("git", "init", "-b", "main", cwd=self.repo)
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Project Brain Test")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "checkout", "-b", "brain/task")
        self.normalizer = GitHistoryNormalizer()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def capture(self):
        return self.normalizer.capture(
            self.repo, expected_branch="brain/task", base_sha=self.base
        )

    def assert_canonical(self, result, expected_text: str) -> None:
        self.assertEqual(git(self.repo, "rev-list", "--count", f"{self.base}..HEAD").stdout.strip(), "1")
        self.assertEqual((self.repo / "result.txt").read_text(encoding="utf-8"), expected_text)
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        self.assertEqual(result.commit, git(self.repo, "rev-parse", "HEAD").stdout.strip())

    def test_normalizes_uncommitted_changes(self) -> None:
        snapshot = self.capture()
        (self.repo / "result.txt").write_text("working tree\n", encoding="utf-8")
        result = self.normalizer.normalize(self.repo, snapshot, message="canonical")
        self.assertEqual(result.source_commits, [])
        self.assert_canonical(result, "working tree\n")

    def test_normalizes_single_agent_commit(self) -> None:
        snapshot = self.capture()
        (self.repo / "result.txt").write_text("one\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "agent one")
        result = self.normalizer.normalize(self.repo, snapshot, message="canonical")
        self.assertEqual(len(result.source_commits), 1)
        self.assert_canonical(result, "one\n")

    def test_normalizes_multiple_agent_commits(self) -> None:
        snapshot = self.capture()
        (self.repo / "result.txt").write_text("one\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "one")
        (self.repo / "result.txt").write_text("two\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "two")
        result = self.normalizer.normalize(self.repo, snapshot, message="canonical")
        self.assertEqual(len(result.source_commits), 2)
        self.assert_canonical(result, "two\n")

    def test_review_revision_appends_without_rewriting_prior_canonical_commit(self) -> None:
        first_snapshot = self.capture()
        (self.repo / "result.txt").write_text("first\n", encoding="utf-8")
        first = self.normalizer.normalize(self.repo, first_snapshot, message="canonical one")
        second_snapshot = self.capture()
        (self.repo / "result.txt").write_text("second\n", encoding="utf-8")
        second = self.normalizer.normalize(self.repo, second_snapshot, message="canonical two")
        self.assertNotEqual(first.commit, second.commit)
        self.assertEqual(
            git(self.repo, "rev-list", "--count", f"{self.base}..HEAD").stdout.strip(),
            "2",
        )
        self.assertEqual(
            git(
                self.repo,
                "merge-base",
                "--is-ancestor",
                first.commit,
                second.commit,
                check=False,
            ).returncode,
            0,
        )

    def test_normalizes_ordinary_cherry_pick(self) -> None:
        git(self.repo, "checkout", "-b", "source", self.base)
        (self.repo / "result.txt").write_text("picked\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "source")
        source = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "checkout", "brain/task")
        snapshot = self.capture()
        git(self.repo, "cherry-pick", source)
        result = self.normalizer.normalize(self.repo, snapshot, message="canonical")
        self.assertEqual(len(result.source_commits), 1)
        self.assert_canonical(result, "picked\n")

    def test_no_changes_is_permanent_error(self) -> None:
        snapshot = self.capture()
        with self.assertRaises(NoChangesError):
            self.normalizer.normalize(self.repo, snapshot, message="canonical")

    def test_branch_switch_is_rejected(self) -> None:
        snapshot = self.capture()
        git(self.repo, "checkout", "-b", "other")
        (self.repo / "result.txt").write_text("wrong branch\n", encoding="utf-8")
        with self.assertRaises(TaskHistoryError):
            self.normalizer.normalize(self.repo, snapshot, message="canonical")

    def test_non_fast_forward_rewrite_is_rejected(self) -> None:
        (self.repo / "result.txt").write_text("initial\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "existing task history")
        snapshot = self.capture()
        git(self.repo, "reset", "--hard", self.base)
        (self.repo / "result.txt").write_text("rewritten\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "rewritten")
        with self.assertRaises(TaskHistoryError):
            self.normalizer.normalize(self.repo, snapshot, message="canonical")

    def test_unresolved_cherry_pick_conflict_is_rejected(self) -> None:
        git(self.repo, "checkout", "-b", "source", self.base)
        (self.repo / "README.md").write_text("source\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "source")
        source = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "checkout", "brain/task")
        snapshot = self.capture()
        (self.repo / "README.md").write_text("task\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "task")
        conflict = git(self.repo, "cherry-pick", source, check=False)
        self.assertNotEqual(conflict.returncode, 0)
        with self.assertRaises(TaskHistoryError):
            self.normalizer.normalize(self.repo, snapshot, message="canonical")


if __name__ == "__main__":
    unittest.main()
