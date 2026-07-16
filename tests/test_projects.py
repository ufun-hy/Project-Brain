from __future__ import annotations

import sys
import unittest
from pathlib import Path

from project_brain.errors import ConfigurationError
from project_brain.projects import ProjectRegistry

from tests.helpers import CoreFixture, create_remote_clone


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.registry = ProjectRegistry(self.fixture.store, self.fixture.runtime)

    def tearDown(self) -> None:
        self.fixture.close()

    def test_registers_multiple_projects_with_stable_ids(self) -> None:
        one, one_remote = create_remote_clone(self.fixture.root, "one")
        two, two_remote = create_remote_clone(self.fixture.root, "two")
        self.registry.register(
            {
                "project_id": "one-id",
                "name": "Project-Brain",
                "repo_path": str(one),
                "remote_url": str(one_remote),
                "codex_command": ["python3", "-V"],
            }
        )
        self.registry.register(
            {
                "project_id": "two-id",
                "name": "kefu-ai",
                "repo_path": str(two),
                "remote_url": str(two_remote),
                "codex_command": ["python3", "-V"],
            }
        )
        projects = self.fixture.store.list_projects()
        self.assertEqual({item["project_id"] for item in projects}, {"one-id", "two-id"})
        self.assertNotEqual(projects[0]["repo_path"], projects[0]["project_id"])
        self.assertTrue(all(Path(item["codex_command"][0]).is_absolute() for item in projects))

    def test_missing_or_non_executable_codex_is_rejected_before_persistence(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "bad-codex-path")
        missing = self.fixture.root / "missing-codex"
        non_executable = self.fixture.root / "non-executable-codex"
        non_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        non_executable.chmod(0o644)
        for path in (missing, non_executable):
            with self.subTest(path=path), self.assertRaises(ConfigurationError):
                self.registry.register(
                    {
                        "project_id": "bad-codex-path",
                        "name": "bad-codex-path",
                        "repo_path": str(repo),
                        "remote_url": str(remote),
                        "codex_command": [str(path), "exec", "-"],
                    }
                )
        self.assertEqual(self.fixture.store.list_projects(), [])

    def test_external_worktree_root_is_rejected(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "external-root")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "external-root",
                    "name": "external-root",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
                    "codex_command": [sys.executable, "-V"],
                    "worktree_root": str(self.fixture.root / "elsewhere"),
                }
            )

    def test_worktree_root_cannot_overlap_registered_checkout(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "overlap")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "overlap",
                    "name": "overlap",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
                    "codex_command": [sys.executable, "-V"],
                    "worktree_root": str(repo / "task-worktrees"),
                }
            )

    def test_literal_secret_command_argument_is_rejected(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "secret-config")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "secret-config",
                    "name": "secret-config",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
                    "codex_command": ["codex", "--api-key", "not-for-sqlite", "exec"],
                }
            )

    def test_project_id_cannot_escape_runtime_worktree_root(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "unsafe-id")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "../outside",
                    "name": "unsafe-id",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
                    "codex_command": ["python3", "-V"],
                }
            )

    def test_invalid_command_shape_is_rejected(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "bad-command")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "bad-command",
                    "name": "bad-command",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
                    "codex_command": "codex exec",
                }
            )


if __name__ == "__main__":
    unittest.main()
