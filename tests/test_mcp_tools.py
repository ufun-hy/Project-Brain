from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from project_brain.models import TaskStatus
from project_brain.mcp.tools import MCPAdapterService

from tests.helpers import CoreFixture, create_remote_clone, git


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def dispatch(self, *, reason: str | None = None):
        self.calls.append(reason)
        return {
            "dispatch_status": "started",
            "code": "ok",
            "worker_pid": 123,
            "log_id": "fake.jsonl",
            "claim_safety": {"claim_safe": True, "blockers": []},
            "next_action": "poll",
        }


class MCPToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.project = self.fixture.add_project(
            verification_commands=[
                {
                    "id": "core-tests",
                    "text": "Core tests pass",
                    "command": ["python3", "-m", "unittest"],
                }
            ]
        )
        self.dispatcher = FakeDispatcher()
        self.service = MCPAdapterService(
            self.fixture.store,
            self.fixture.runtime,
            dispatcher=self.dispatcher,  # type: ignore[arg-type]
        )

    def tearDown(self) -> None:
        self.fixture.close()

    @staticmethod
    def _create_value(task_id: str = "mcp-task") -> dict[str, object]:
        return {
            "task_id": task_id,
            "project_id": "project-one",
            "dedupe_key": task_id,
            "revision": 1,
            "goal": "Update controlled documentation",
            "task_type": "codex",
            "acceptance_criteria": [
                {
                    "id": "core-tests-pass",
                    "text": "Core tests pass",
                    "verification_id": "core-tests",
                }
            ],
            "prompt": "Update one documentation page and add tests.",
        }

    def test_projects_and_health_omit_paths_commands_and_secrets(self) -> None:
        self.assertFalse(self.fixture.runtime.lock_file.exists())
        projects = self.service.projects_list()
        health = self.service.system_health()
        self.assertFalse(self.fixture.runtime.lock_file.exists())
        rendered = json.dumps({"projects": projects, "health": health})
        self.assertNotIn("repo_path", rendered)
        self.assertNotIn("worktree_root", rendered)
        self.assertNotIn("codex_command", rendered)
        self.assertNotIn(str(self.fixture.root), rendered)
        self.assertEqual(projects["projects"][0]["project_id"], "project-one")

    def test_create_is_canonical_idempotent_and_audited(self) -> None:
        first = self.service.tasks_create(self._create_value())
        second = self.service.tasks_create(self._create_value())
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "duplicate")
        task = self.fixture.store.get_task("mcp-task")
        self.assertEqual(task["source_type"], "mcp")
        self.assertEqual(task["task_type"], "codex")
        self.assertEqual(task["payload"]["prompt"], "Update one documentation page and add tests.")
        self.assertNotIn("payload", json.dumps(first))
        self.assertEqual(
            [
                event["payload"]["outcome"]
                for event in self.fixture.store.list_events("mcp-task")
                if event["event_type"] == "mcp_task_create_requested"
            ],
            ["duplicate"],
        )
        self.assertEqual(
            self.fixture.store.list_events("mcp-task")[0]["payload"]["source_type"],
            "mcp",
        )

    def test_create_writes_only_control_plane_state_not_checkout_or_worktree(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "mcp-boundary")
        self.fixture.add_project(
            repo_path=str(repo),
            remote_url=str(remote),
            verification_commands=[
                {
                    "id": "core-tests",
                    "text": "Core tests pass",
                    "command": ["python3", "-m", "unittest"],
                }
            ],
        )
        head_before = git(repo, "rev-parse", "HEAD").stdout.strip()
        status_before = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
        result = self.service.tasks_create(self._create_value("control-plane-only"))
        self.assertEqual(result["status"], "created")
        self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(
            git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout,
            status_before,
        )
        task = self.fixture.store.get_task("control-plane-only")
        self.assertIsNone(task["worktree_path"])
        self.assertEqual(list(self.fixture.runtime.worktrees_dir.rglob("*")), [])

    def test_create_rejects_deep_control_fields_before_persistence(self) -> None:
        forbidden_fields = (
            "command",
            "argv",
            "shell",
            "cwd",
            "environment",
            "repo_path",
            "worktree_path",
            "codex_command",
        )
        for field in forbidden_fields:
            value = self._create_value(f"bad-{field.replace('_', '-')}")
            criterion = value["acceptance_criteria"][0]  # type: ignore[index]
            criterion["metadata"] = {"nested": {field: "forbidden"}}  # type: ignore[index]
            with self.subTest(field=field):
                result = self.service.tasks_create(value)
                self.assertEqual(result["code"], "validation")
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_create_rejects_unregistered_project_unknown_verification_invalid_id_expiry_and_secret(self) -> None:
        values = []
        unregistered = self._create_value("unknown-project")
        unregistered["project_id"] = "missing"
        values.append((unregistered, "not_found"))
        unknown_verification = self._create_value("unknown-check")
        unknown_verification["acceptance_criteria"][0]["verification_id"] = "missing"  # type: ignore[index]
        values.append((unknown_verification, "validation"))
        invalid_id = self._create_value("valid-temporary")
        invalid_id["task_id"] = "../escape"
        values.append((invalid_id, "validation"))
        expired = self._create_value("expired-mcp")
        expired["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        values.append((expired, "validation"))
        secret = self._create_value("secret-mcp")
        secret["prompt"] = "Use sk-abcdefghijklmnopqrstuvwxyz123456 in the task"
        values.append((secret, "validation"))
        for value, code in values:
            with self.subTest(task_id=value["task_id"]):
                result = self.service.tasks_create(value)
                self.assertEqual(result["code"], code)
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_tasks_list_clamps_limit_and_task_get_bounds_events(self) -> None:
        for index in range(105):
            self.fixture.add_task(f"task-{index:03d}")
        listed = self.service.tasks_list(limit=1_000)
        self.assertEqual(listed["limit"], 100)
        self.assertEqual(len(listed["tasks"]), 100)
        for index in range(150):
            self.fixture.store.record_event(
                task_id="task-000",
                event_type="test_event",
                payload={
                    "reason": f"bounded-{index}",
                    "command": ["must", "not", "leak"],
                    "repo_path": str(self.fixture.root),
                },
            )
        detail = self.service.tasks_get(task_id="task-000", recent_event_limit=1_000)
        self.assertEqual(len(detail["data"]["events"]), 100)
        rendered = json.dumps(detail)
        self.assertNotIn("must", rendered)
        self.assertNotIn("repo_path", rendered)
        self.assertNotIn("payload\": {\"prompt", rendered)
        self.assertLessEqual(len(rendered.encode()), 96 * 1024 + 1_000)

    def test_review_is_exact_head_atomic_and_never_dispatches(self) -> None:
        self.fixture.add_task("review-mcp")
        self.fixture.store.claim_next()
        head = "a" * 40
        self.fixture.store.set_task_fields("review-mcp", head_sha=head, commit=head)
        self.fixture.store.transition("review-mcp", TaskStatus.AWAITING_REVIEW)
        wrong = self.service.tasks_review(
            {
                "task_id": "review-mcp",
                "head_sha": "b" * 40,
                "verdict": "needs_changes",
                "findings": [
                    {
                        "severity": "major",
                        "evidence": "The expected guard is missing.",
                        "requirement": "Add the guard and its regression test.",
                    }
                ],
            }
        )
        self.assertEqual(wrong["code"], "validation")
        result = self.service.tasks_review(
            {
                "task_id": "review-mcp",
                "head_sha": head,
                "verdict": "needs_changes",
                "findings": [
                    {
                        "severity": "major",
                        "file": "src/project_brain/example.py",
                        "evidence": "The expected guard is missing.",
                        "requirement": "Add the guard and its regression test.",
                    }
                ],
            }
        )
        self.assertEqual(result["status"], TaskStatus.NEEDS_CHANGES.value)
        self.assertEqual(len(self.fixture.store.list_reviews("review-mcp")), 1)
        self.assertEqual(self.dispatcher.calls, [])

    def test_recovery_preview_is_read_only_and_exposes_no_resolution(self) -> None:
        self.fixture.add_task("preview-mcp")
        self.fixture.store.claim_next()
        before_task = self.fixture.store.get_task("preview-mcp")
        before_events = self.fixture.store.list_events("preview-mcp")
        result = self.service.tasks_recovery_preview(task_id="preview-mcp")
        after_task = self.fixture.store.get_task("preview-mcp")
        after_events = self.fixture.store.list_events("preview-mcp")
        self.assertEqual(result["dry_run_action"]["action"], "would_recover")
        self.assertTrue(result["claim_blocker"]["blocked"])
        self.assertEqual(before_task, after_task)
        self.assertEqual(before_events, after_events)
        rendered = json.dumps(result)
        for forbidden in ("terminate_agent", "confirm_no_agent", '"resume"', '"cancel"'):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
