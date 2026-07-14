from __future__ import annotations

import json
import unittest

from project_brain.errors import ConfigurationError
from project_brain.projects import ProjectRegistry, stable_legacy_project_id

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
            }
        )
        self.registry.register(
            {
                "project_id": "two-id",
                "name": "kefu-ai",
                "repo_path": str(two),
                "remote_url": str(two_remote),
            }
        )
        projects = self.fixture.store.list_projects()
        self.assertEqual({item["project_id"] for item in projects}, {"one-id", "two-id"})
        self.assertNotEqual(projects[0]["repo_path"], projects[0]["project_id"])

    def test_legacy_import_preserves_source_file(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "legacy")
        source = self.fixture.root / "bridge-config.json"
        source.write_text(
            json.dumps(
                {
                    "projects": {
                        "Project-Brain": {
                            "path": str(repo),
                            "base_branch": "main",
                            "remote_url": str(remote),
                            "auto_push": False,
                            "auto_pr": False,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        before = source.read_bytes()
        processed = self.fixture.root / "processed.json"
        failures = self.fixture.root / "failures.json"
        processed.write_text('{"processed_message_ids":["old"]}\n', encoding="utf-8")
        failures.write_text('{"old":{"attempt_count":2}}\n', encoding="utf-8")
        processed_before = processed.read_bytes()
        failures_before = failures.read_bytes()
        imported = self.registry.import_bridge_v2(source)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(processed.read_bytes(), processed_before)
        self.assertEqual(failures.read_bytes(), failures_before)
        self.assertEqual(imported[0]["project_id"], stable_legacy_project_id("Project-Brain"))
        self.assertFalse(imported[0]["auto_push"])

    def test_worktree_root_cannot_overlap_registered_checkout(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "overlap")
        with self.assertRaises(ConfigurationError):
            self.registry.register(
                {
                    "project_id": "overlap",
                    "name": "overlap",
                    "repo_path": str(repo),
                    "remote_url": str(remote),
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
