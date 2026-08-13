from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from project_brain.models import TaskStatus
from project_brain.mcp.tools import MCPAdapterService
from project_brain.store import TaskStore

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

    def _prepare_recovery_blocked_task(self) -> tuple[str, str, str]:
        old = self.fixture.add_task(
            "blocked-publication",
            dedupe_key="publication-flow",
            revision=1,
        )
        old_task_id = str(old["task_id"])
        self.fixture.store.claim_next()
        published = "a" * 40
        candidate = "c" * 40
        self.fixture.store.set_task_fields(
            old_task_id,
            branch="brain/blocked-publication",
            commit=published,
            head_sha=published,
        )
        self.fixture.store.record_candidate(
            old_task_id,
            candidate,
            publication_base_sha=published,
        )
        self.fixture.store.record_publication_conflict(
            old_task_id,
            {
                "branch": "brain/blocked-publication",
                "expected_remote_head_sha": published,
                "observed_remote_head_sha": "b" * 40,
                "publication_base_sha": published,
                "candidate_sha": candidate,
            },
        )
        self.fixture.store.block_running_task(
            old_task_id,
            reason="publication conflict requires a new revision",
        )
        return old_task_id, published, candidate

    def _superseding_value(self, task_id: str) -> dict[str, object]:
        replacement = self._create_value(task_id)
        replacement.update(
            {
                "dedupe_key": "publication-flow",
                "revision": 2,
                "supersedes": "blocked-publication",
                "workflow_kind": "implement",
            }
        )
        return replacement

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
        self.assertEqual(projects["projects"][0]["config_revision"], 1)
        self.assertEqual(len(projects["projects"][0]["config_sha256"]), 12)

    def test_project_verification_catalog_exposes_no_command_or_path(self) -> None:
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "safe-check",
                "text": "Safe check",
                "command": ["/private/check", "--secret-from-env"],
                "always_run": True,
            }
        ]
        self.fixture.store.register_project(project)
        projects = self.service.projects_list()
        catalog = projects["projects"][0]["verification_catalog"]
        self.assertEqual(catalog, [{"id": "safe-check", "text": "Safe check", "always_run": True}])
        rendered = json.dumps(projects)
        self.assertNotIn("/private/check", rendered)
        self.assertNotIn("command", rendered)

    def test_draft_coverage_is_derived_from_frozen_profile(self) -> None:
        value = self._create_value("coverage")
        value["workflow_kind"] = "implement"
        value["acceptance_criteria"] = [
            {"id": "manual", "text": "Human review"},
            {"id": "trusted", "text": "Trusted check", "verification_id": "core-tests"},
        ]
        result = self.service.tasks_create_draft(value)
        coverage = result["execution_plan"]["verification_coverage"]
        self.assertEqual(coverage["criteria"][0]["evidence_type"], "manual_required")
        self.assertEqual(coverage["criteria"][1]["evidence_type"], "trusted_project_command")
        self.assertTrue(coverage["criteria"][1]["covered_by_frozen_project_configuration"])

    def test_create_is_canonical_idempotent_and_audited(self) -> None:
        first = self.service.tasks_create(self._create_value())
        second = self.service.tasks_create(self._create_value())
        self.assertEqual(first["status"], "draft_created")
        self.assertEqual(second["status"], "draft_replayed")
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertNotEqual(
            first["confirmation"]["confirmation_token"],
            second["confirmation"]["confirmation_token"],
        )
        task = self.fixture.store.get_task("mcp-task")
        self.assertEqual(task["source_type"], "mcp")
        self.assertEqual(task["task_type"], "codex")
        self.assertEqual(task["payload"]["prompt"], "Update one documentation page and add tests.")
        self.assertNotIn("payload", json.dumps(first))
        self.assertEqual(first["task"]["project_config_revision"], 1)
        self.assertEqual(len(first["task"]["project_config_sha256"]), 12)
        self.assertEqual(first["task"]["revision"], 1)
        self.assertEqual(first["task"]["plan_hash"], task["dispatch_plan_sha256"])
        self.assertEqual(
            first["task"]["dispatch_confirmation"],
            {"required": True, "confirmed": False, "confirmed_at": None},
        )
        self.assertIn(
            "mcp_task_confirmation_reissued",
            [event["event_type"] for event in self.fixture.store.list_events("mcp-task")],
        )
        stale = self.service.tasks_confirm(
            {
                "task_id": "mcp-task",
                "confirmation_token": first["confirmation"]["confirmation_token"],
                "expected_plan_hash": first["plan_hash"],
            }
        )
        self.assertEqual(stale["code"], "validation")
        confirmed = self.service.tasks_confirm(
            {
                "task_id": "mcp-task",
                "confirmation_token": second["confirmation"]["confirmation_token"],
                "expected_plan_hash": second["plan_hash"],
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")
        replay_after_confirmation = self.service.tasks_create(self._create_value())
        self.assertEqual(replay_after_confirmation["status"], "duplicate")
        self.assertNotIn("confirmation", replay_after_confirmation)

        changed = self._create_value()
        changed["prompt"] = "A different request must not reuse the same identity."
        conflict = self.service.tasks_create(changed)
        self.assertEqual(conflict["code"], "state_conflict")
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
        self.assertEqual(result["status"], "draft_created")
        self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(
            git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout,
            status_before,
        )
        task = self.fixture.store.get_task("control-plane-only")
        self.assertIsNone(task["worktree_path"])
        self.assertEqual(list(self.fixture.runtime.worktrees_dir.rglob("*")), [])

    def test_draft_requires_confirmation_and_can_link_analysis_to_implementation(self) -> None:
        analyze = self._create_value("analyze-mcp")
        analyze["workflow_kind"] = "analyze"
        draft = self.service.tasks_create_draft(analyze)
        self.assertEqual(draft["status"], "draft_created")
        self.assertTrue(draft["confirmation"]["required"])
        self.assertEqual(self.fixture.store.claim_next(), None)

        token = draft["confirmation"]["confirmation_token"]
        wrong_plan = self.service.tasks_confirm(
            {
                "task_id": "analyze-mcp",
                "confirmation_token": token,
                "expected_plan_hash": "0" * 64,
            }
        )
        self.assertEqual(wrong_plan["code"], "state_conflict")
        confirmed = self.service.tasks_confirm(
            {
                "task_id": "analyze-mcp",
                "confirmation_token": token,
                "expected_plan_hash": draft["plan_hash"],
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")
        claimed = self.fixture.store.claim_next()
        self.assertEqual(claimed["task_id"], "analyze-mcp")
        analysis_result = {
            "schema_version": 1,
            "kind": "analysis",
            "summary": "Implement the bounded MCP intake changes.",
            "completed_at": "2026-08-09T00:00:00+00:00",
        }
        self.fixture.store.set_task_result("analyze-mcp", analysis_result)
        self.fixture.store.transition(
            "analyze-mcp",
            TaskStatus.COMPLETED,
            event_type="analysis_completed",
        )
        source_detail = self.service.tasks_get(task_id="analyze-mcp")
        self.assertEqual(source_detail["data"]["analysis"]["task_id"], "analyze-mcp")
        self.assertEqual(
            source_detail["data"]["analysis"]["result_summary"],
            analysis_result["summary"],
        )
        self.assertEqual(
            len(source_detail["data"]["task"]["analysis_result_sha256"]), 64
        )

        implementation = self._create_value("implement-mcp")
        implementation["workflow_kind"] = "implement"
        implementation["analysis_task_id"] = "analyze-mcp"
        linked = self.service.tasks_create_draft(implementation)
        self.assertEqual(linked["status"], "draft_created")
        detail = self.service.tasks_get(task_id="implement-mcp")
        self.assertEqual(detail["data"]["task"]["analysis_task_id"], "analyze-mcp")
        self.assertEqual(detail["data"]["analysis"]["task_id"], "analyze-mcp")
        self.assertEqual(
            detail["data"]["analysis"]["result_summary"],
            analysis_result["summary"],
        )
        self.assertEqual(len(detail["data"]["analysis"]["fixed_result_sha256"]), 64)

    def test_draft_confirmation_rejects_wrong_token_and_non_analysis_parent(self) -> None:
        draft = self._create_value("gated-mcp")
        draft["workflow_kind"] = "analyze"
        result = self.service.tasks_create_draft(draft)
        wrong = self.service.tasks_confirm(
            {
                "task_id": "gated-mcp",
                "confirmation_token": "x" * 43,
                "expected_plan_hash": result["plan_hash"],
            }
        )
        self.assertEqual(wrong["code"], "validation")
        self.assertEqual(self.fixture.store.claim_next(), None)

        normal = self._create_value("not-analysis")
        normal["workflow_kind"] = "implement"
        self.service.tasks_create_draft(normal)
        invalid = self._create_value("bad-analysis-link")
        invalid["workflow_kind"] = "implement"
        invalid["analysis_task_id"] = "not-analysis"
        self.assertEqual(self.service.tasks_create_draft(invalid)["code"], "validation")
        self.assertEqual(result["task"]["dispatch_confirmation"]["confirmed"], False)

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

    def test_legacy_create_cannot_bypass_draft_confirmation_or_supersede(self) -> None:
        launches: list[list[str]] = []

        def unexpected_launch(argv, **_kwargs):
            launches.append(list(argv))
            raise AssertionError("blocked dispatch must not start a worker")

        from project_brain.mcp.dispatch import OneShotDispatcher

        dispatcher = OneShotDispatcher(self.fixture.store, self.fixture.runtime, popen_factory=unexpected_launch)
        service = MCPAdapterService(
            self.fixture.store,
            self.fixture.runtime,
            dispatcher=dispatcher,
        )
        original = self._create_value("mcp-owned")
        original["dedupe_key"] = "mcp-owned-flow"
        original["revision"] = 4
        self.assertEqual(service.tasks_create(original)["status"], "draft_created")
        self.assertEqual(self.fixture.store.claim_next(), None)

        replacement = self._create_value("mcp-owned-replacement")
        replacement["dedupe_key"] = "mcp-owned-flow"
        replacement["revision"] = 5
        replacement["supersedes"] = "mcp-owned"
        conflict = service.tasks_create(replacement)
        self.assertEqual(conflict["status"], "error")
        self.assertEqual(conflict["code"], "state_conflict")
        self.assertEqual(
            self.fixture.store.get_task("mcp-owned")["status"],
            TaskStatus.PENDING.value,
        )
        self.assertNotIn(
            "mcp-owned-replacement",
            {task["task_id"] for task in self.fixture.store.list_tasks()},
        )

        dispatch = service.queue_dispatch_next(reason="confirm blocker remains visible")
        self.assertEqual(dispatch["dispatch_status"], "idle")
        self.assertEqual(launches, [])

    def test_recovery_blocked_public_superseding_draft_requires_confirmation(self) -> None:
        old = self.fixture.add_task(
            "blocked-publication",
            dedupe_key="publication-flow",
            revision=1,
        )
        self.fixture.store.claim_next()
        published = "a" * 40
        candidate = "c" * 40
        self.fixture.store.set_task_fields(
            old["task_id"],
            branch="brain/blocked-publication",
            commit=published,
            head_sha=published,
        )
        self.fixture.store.record_candidate(
            old["task_id"], candidate, publication_base_sha=published
        )
        self.fixture.store.record_publication_conflict(
            old["task_id"],
            {
                "branch": "brain/blocked-publication",
                "expected_remote_head_sha": published,
                "observed_remote_head_sha": "b" * 40,
                "publication_base_sha": published,
                "candidate_sha": candidate,
            },
        )
        self.fixture.store.block_running_task(
            old["task_id"], reason="publication conflict requires a new revision"
        )

        replacement = self._create_value("publication-replacement")
        replacement.update(
            {
                "dedupe_key": "publication-flow",
                "revision": 2,
                "supersedes": old["task_id"],
                "workflow_kind": "implement",
            }
        )
        draft = self.service.tasks_create_draft(replacement)
        self.assertEqual(draft["status"], "draft_created")
        self.assertEqual(
            self.fixture.store.get_task(old["task_id"])["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        stored = self.fixture.store.get_task("publication-replacement")
        self.assertEqual(stored["base_sha"], published)
        self.assertIsNone(stored["canonical_published_head_sha"])
        self.assertIsNone(self.fixture.store.claim_next())

        confirmed = self.service.tasks_confirm(
            {
                "task_id": "publication-replacement",
                "confirmation_token": draft["confirmation"]["confirmation_token"],
                "expected_plan_hash": draft["plan_hash"],
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(
            self.fixture.store.get_task(old["task_id"])["status"],
            TaskStatus.SUPERSEDED.value,
        )
        preserved = self.fixture.store.get_task(old["task_id"])
        self.assertEqual(preserved["publication_conflict"]["candidate_sha"], candidate)
        self.assertEqual(self.fixture.store.claim_next()["task_id"], "publication-replacement")

    def test_recovery_blocked_superseding_draft_exact_replay_is_idempotent(self) -> None:
        old_task_id, published, candidate = self._prepare_recovery_blocked_task()
        replacement = self._superseding_value("publication-replay")

        first = self.service.tasks_create_draft(replacement)
        replay = self.service.tasks_create_draft(replacement)

        self.assertEqual(first["status"], "draft_created")
        self.assertEqual(replay["status"], "draft_replayed")
        self.assertEqual(first["plan_hash"], replay["plan_hash"])
        self.assertNotEqual(
            first["confirmation"]["confirmation_token"],
            replay["confirmation"]["confirmation_token"],
        )
        self.assertEqual(
            self.fixture.store.get_task(old_task_id)["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        stored = self.fixture.store.get_task("publication-replay")
        self.assertEqual(stored["base_sha"], published)
        self.assertEqual(stored["supersedes"], old_task_id)
        events = self.fixture.store.list_events("publication-replay")
        self.assertEqual(
            [event["event_type"] for event in events].count("mcp_task_draft_created"),
            1,
        )
        self.assertEqual(
            [event["event_type"] for event in events].count(
                "mcp_task_confirmation_reissued"
            ),
            1,
        )

        stale = self.service.tasks_confirm(
            {
                "task_id": "publication-replay",
                "confirmation_token": first["confirmation"]["confirmation_token"],
                "expected_plan_hash": first["plan_hash"],
            }
        )
        self.assertEqual(stale["code"], "validation")
        confirmed = self.service.tasks_confirm(
            {
                "task_id": "publication-replay",
                "confirmation_token": replay["confirmation"]["confirmation_token"],
                "expected_plan_hash": replay["plan_hash"],
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")
        duplicate = self.service.tasks_create_draft(replacement)
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertNotIn("confirmation", duplicate)

        preserved = self.fixture.store.get_task(old_task_id)
        self.assertEqual(preserved["status"], TaskStatus.SUPERSEDED.value)
        self.assertEqual(preserved["publication_conflict"]["candidate_sha"], candidate)
        self.assertEqual(
            [
                event["event_type"]
                for event in self.fixture.store.list_events(old_task_id)
            ].count("task_superseded"),
            1,
        )

    def test_recovery_blocked_superseding_draft_survives_database_reopen(self) -> None:
        old_task_id, published, candidate = self._prepare_recovery_blocked_task()
        replacement = self._superseding_value("publication-reopen")
        draft = self.service.tasks_create_draft(replacement)

        reopened_store = TaskStore(self.fixture.runtime.database)
        reopened_store.initialize()
        reopened_service = MCPAdapterService(
            reopened_store,
            self.fixture.runtime,
            dispatcher=self.dispatcher,  # type: ignore[arg-type]
        )
        self.assertEqual(
            reopened_store.get_task(old_task_id)["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        reopened_draft = reopened_store.get_task("publication-reopen")
        self.assertEqual(reopened_draft["status"], TaskStatus.PENDING.value)
        self.assertEqual(reopened_draft["base_sha"], published)
        self.assertEqual(reopened_draft["supersedes"], old_task_id)

        replay = reopened_service.tasks_create_draft(replacement)
        self.assertEqual(replay["status"], "draft_replayed")
        stale = reopened_service.tasks_confirm(
            {
                "task_id": "publication-reopen",
                "confirmation_token": draft["confirmation"]["confirmation_token"],
                "expected_plan_hash": draft["plan_hash"],
            }
        )
        self.assertEqual(stale["code"], "validation")
        confirmed = reopened_service.tasks_confirm(
            {
                "task_id": "publication-reopen",
                "confirmation_token": replay["confirmation"]["confirmation_token"],
                "expected_plan_hash": replay["plan_hash"],
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")

        verified_store = TaskStore(self.fixture.runtime.database)
        verified_store.initialize()
        preserved = verified_store.get_task(old_task_id)
        verified_draft = verified_store.get_task("publication-reopen")
        self.assertEqual(preserved["status"], TaskStatus.SUPERSEDED.value)
        self.assertEqual(preserved["publication_conflict"]["candidate_sha"], candidate)
        self.assertEqual(verified_draft["base_sha"], published)
        self.assertIsNotNone(verified_draft["dispatch_confirmed_at"])
        self.assertEqual(
            [event["event_type"] for event in verified_store.list_events(old_task_id)].count(
                "task_superseded"
            ),
            1,
        )

    def test_recovery_blocked_superseding_draft_is_concurrent_and_atomic(self) -> None:
        old_task_id, published, candidate = self._prepare_recovery_blocked_task()
        replacement = self._superseding_value("publication-concurrent")

        with ThreadPoolExecutor(max_workers=2) as executor:
            drafts = list(
                executor.map(
                    lambda _: self.service.tasks_create_draft(dict(replacement)),
                    range(2),
                )
            )
        self.assertEqual(
            sorted(result["status"] for result in drafts),
            ["draft_created", "draft_replayed"],
        )
        self.assertEqual(
            self.fixture.store.get_task(old_task_id)["status"],
            TaskStatus.RECOVERY_BLOCKED.value,
        )
        stored = self.fixture.store.get_task("publication-concurrent")
        self.assertEqual(stored["base_sha"], published)
        self.assertEqual(stored["supersedes"], old_task_id)
        self.assertEqual(
            [
                task["task_id"]
                for task in self.fixture.store.list_tasks()
                if task["dedupe_key"] == "publication-flow"
                and task["revision"] == 2
            ],
            ["publication-concurrent"],
        )

        final_replay = self.service.tasks_create_draft(replacement)
        confirmation = {
            "task_id": "publication-concurrent",
            "confirmation_token": final_replay["confirmation"]["confirmation_token"],
            "expected_plan_hash": final_replay["plan_hash"],
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            confirmations = list(
                executor.map(
                    lambda _: self.service.tasks_confirm(dict(confirmation)),
                    range(2),
                )
            )
        self.assertEqual(
            [result["status"] for result in confirmations],
            ["confirmed", "confirmed"],
        )
        preserved = self.fixture.store.get_task(old_task_id)
        self.assertEqual(preserved["status"], TaskStatus.SUPERSEDED.value)
        self.assertEqual(preserved["publication_conflict"]["candidate_sha"], candidate)
        self.assertEqual(
            [
                event["event_type"]
                for event in self.fixture.store.list_events(old_task_id)
            ].count("task_superseded"),
            1,
        )
        new_events = self.fixture.store.list_events("publication-concurrent")
        self.assertEqual(
            [event["event_type"] for event in new_events].count(
                "mcp_task_dispatch_confirmed"
            ),
            1,
        )

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

    def test_redispatch_requires_current_remote_head_and_is_idempotent(self) -> None:
        repo, remote = create_remote_clone(self.fixture.root, "redispatch-mcp")
        project = self.fixture.add_project(
            project_id="redispatch-project",
            repo_path=str(repo),
            remote_url=str(remote),
        )
        branch = "brain/redispatch-mcp"
        published = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "branch", branch, published)
        git(repo, "push", "origin", branch)
        self.fixture.add_task(
            "redispatch-mcp",
            project_id=project["project_id"],
        )
        self.fixture.store.claim_next()
        self.fixture.store.set_task_fields(
            "redispatch-mcp",
            branch=branch,
            commit=published,
            head_sha=published,
        )
        self.fixture.store.transition("redispatch-mcp", TaskStatus.AWAITING_REVIEW)
        self.fixture.store.transition("redispatch-mcp", TaskStatus.NEEDS_CHANGES)
        value = {
            "task_id": "redispatch-mcp",
            "expected_remote_head_sha": published,
            "redispatch_plan_sha256": "1" * 64,
            "idempotency_key": "redispatch-mcp-revision-2",
        }
        first = self.service.tasks_redispatch(value)
        second = self.service.tasks_redispatch(value)
        self.assertEqual(first["status"], "redispatch_authorized")
        self.assertEqual(second["status"], "redispatch_authorized")
        self.assertEqual(
            self.fixture.store.get_task("redispatch-mcp")["status"],
            TaskStatus.RETRY_PENDING.value,
        )
        self.assertEqual(
            [
                item["event_type"]
                for item in self.fixture.store.list_events("redispatch-mcp")
            ].count("explicit_redispatch_authorized"),
            1,
        )

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
