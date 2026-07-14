from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from project_brain.actions import run_named_command, write_files
from project_brain.errors import InvalidPathError, InvalidTaskError


class ActionSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_write_files_rejects_parent_traversal(self) -> None:
        with self.assertRaises(InvalidPathError):
            write_files(
                self.worktree,
                {"files": [{"path": "../outside.txt", "content": "no"}]},
            )

    def test_write_files_rejects_git_metadata(self) -> None:
        with self.assertRaises(InvalidPathError):
            write_files(
                self.worktree,
                {"files": [{"path": ".git/config", "content": "no"}]},
            )

    def test_command_task_accepts_only_local_allowlist_names(self) -> None:
        project = {"allowed_commands": {"safe": [sys.executable, "-c", "print('ok')"]}}
        result = run_named_command(self.worktree, {"command": "safe"}, project)
        self.assertIn("ok", result["stdout"])
        with self.assertRaises(InvalidTaskError):
            run_named_command(
                self.worktree,
                {"command": "rm -rf /"},
                project,
            )


if __name__ == "__main__":
    unittest.main()
