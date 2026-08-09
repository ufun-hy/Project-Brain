from __future__ import annotations

import json
import sys
import threading
import unittest
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from project_brain.engine import TaskEngine
from project_brain.errors import InvalidTaskError, StateConflictError
from project_brain.local_tasks import (
    LocalTaskManager,
    _canonical_json,
    validate_local_task_request,
)
from project_brain.locking import RuntimeLock
from project_brain.models import TaskStatus
from project_brain.store import TaskStore

from tests.helpers import CoreFixture, create_remote_clone, executable_script, git


def healthy(*_args):
    return {
        "status": "healthy",
        "ready": True,
        "checks": [],
        "blockers": [],
        "external_chatgpt_acceptance": "pending",
    }


class MutableReadiness:
    ready = True

    def __call__(self, *_args):
        return {
            "status": "healthy" if self.ready else "unhealthy",
            "ready": self.ready,
            "checks": [],
            "blockers": [] if self.ready else [{"name": "test", "status": "failed"}],
            "external_chatgpt_acceptance": "pending",
        }


class LocalTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "local-task")
        self.project = self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=False,
            auto_pr=False,
        )
        self.now = datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc)
        self.manager = LocalTaskManager(
            self.fixture.store,
            self.fixture.runtime,
            readiness_provider=healthy,
            clock=lambda: self.now,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def request(self, task_type: str = "analysis", **overrides):
        delivery = (
            {"commit": False, "push": False, "draft_pr": False}
            if task_type == "analysis"
            else {"commit": True, "push": False, "draft_pr": False}
        )
        value = {
            "schema_version": 1,
            "source": "local_app",
            "project_id": "project-one",
            "task_type": task_type,
            "goal": "Review the repository and report concrete findings.",
            "acceptance_criteria": ["Return actionable evidence"],
            "delivery": delivery,
        }
        value.update(overrides)
        return value

    def planned(
        self,
        request: dict,
        manager: LocalTaskManager | None = None,
    ) -> tuple[dict, dict[str, str]]:
        response = (manager or self.manager).plan(request)
        plan = response["plan"]
        return response, {
            "plan_token": plan["plan_token"],
            "expected_plan_hash": plan["plan_hash"],
        }

    def test_strict_schema_accepts_only_source_neutral_fields(self) -> None:
        request = self.request()
        self.assertEqual(validate_local_task_request(request)["source"], "local_app")
        for forbidden in (
            "command",
            "argv",
            "cwd",
            "environment",
            "sql",
            "path",
            "worktree_path",
            "branch_name",
            "executable",
            "github_token",
            "tunnel_token",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(InvalidTaskError):
                validate_local_task_request({**request, forbidden: "unsafe"})

    def test_goal_and_criteria_unicode_limits_are_enforced(self) -> None:
        with self.assertRaises(InvalidTaskError):
            validate_local_task_request(self.request(goal="short"))
        with self.assertRaises(InvalidTaskError):
            validate_local_task_request(
                self.request(acceptance_criteria=["验" * 4001, "收" * 4000])
            )

    def test_core_is_unicode_authority_for_whitespace_cjk_emoji_and_combining(self) -> None:
        goal = "\u3000分析 e\u0301 与 👩‍💻 组合字符，不要修改文件。\u00a0"
        normalized = validate_local_task_request(self.request(goal=goal))
        canonical = "分析 e\u0301 与 👩‍💻 组合字符，不要修改文件。"
        self.assertEqual(normalized["goal"], canonical)
        response, confirmation = self.planned(self.request(goal=goal))
        self.assertEqual(response["plan"]["canonical_goal"], canonical)
        self.assertEqual(response["plan"]["canonical_goal_length"], len(canonical))
        created = self.manager.create(confirmation)
        self.assertEqual(created["task"]["goal"], canonical)

        for length, valid in ((9, False), (10, True), (8000, True), (8001, False)):
            with self.subTest(length=length):
                request = self.request(goal="界" * length)
                if valid:
                    self.assertEqual(len(validate_local_task_request(request)["goal"]), length)
                else:
                    with self.assertRaises(InvalidTaskError) as raised:
                        validate_local_task_request(request)
                    self.assertEqual(raised.exception.error_code, "task_goal_invalid")
                    self.assertEqual(raised.exception.constraints["actual"], length)

    def test_plan_binds_exact_remote_project_profile_and_delivery(self) -> None:
        response = self.manager.plan(self.request())
        plan = response["plan"]
        self.assertEqual(response["status"], "planned")
        self.assertEqual(
            plan["base_sha"], git(self.repo, "rev-parse", "origin/main").stdout.strip()
        )
        self.assertEqual(plan["execution_profile_revision"], 1)
        self.assertEqual(
            plan["execution_profile_sha256"], self.project["config_sha256"]
        )
        self.assertEqual(plan["repository_path"], str(self.repo.resolve()))
        self.assertTrue(plan["plan_token"].startswith("local-v2:"))
        reviewed = {
            key: value
            for key, value in plan.items()
            if key not in {"plan_token", "plan_hash", "token_fingerprint"}
        }
        self.assertEqual(
            plan["plan_hash"],
            sha256(_canonical_json(reviewed).encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            plan["token_fingerprint"],
            sha256(plan["plan_token"].encode("utf-8")).hexdigest()[:12],
        )
        self.assertEqual(plan["contract_version"], "1.2.0")
        self.assertEqual(plan["external_chatgpt_acceptance"], "pending")

    def test_plan_token_is_never_persisted_in_plaintext(self) -> None:
        response, _ = self.planned(self.request())
        token = response["plan"]["plan_token"]
        with self.fixture.store.connect() as connection:
            row = connection.execute("SELECT * FROM local_task_plans").fetchone()
        self.assertEqual(
            row["plan_token_sha256"], sha256(token.encode("utf-8")).hexdigest()
        )
        self.assertNotIn(token, row["plan_json"])
        self.assertNotIn(token.encode("utf-8"), self.fixture.runtime.database.read_bytes())

    def test_default_readiness_accepts_the_runtime_lock_held_by_confirmation(self) -> None:
        manager = LocalTaskManager(
            self.fixture.store,
            self.fixture.runtime,
            clock=lambda: self.now,
        )
        service = {
            "status": "running",
            "helper_executable": "/managed/project-brain",
            "services": [{"name": "worker", "state": "running"}],
        }
        with patch("project_brain.local_tasks.ServiceManager.status", return_value=service):
            _, confirmation = self.planned(self.request(), manager)
            with RuntimeLock(self.fixture.runtime.lock_file):
                created = manager.create(confirmation)
        self.assertEqual(created["status"], "created")
        self.assertEqual(len(self.fixture.store.list_tasks()), 1)

    def test_confirmation_uses_only_plan_authority_and_preserves_exact_chinese_goal(self) -> None:
        goal = "分析当前项目的 README 和代码目录，说明项目用途、主要模块和当前风险。不要修改任何文件。"
        request = self.request(goal=goal)
        response, confirmation = self.planned(request)
        request["goal"] = "客户端在计划后发生的修改绝不能进入任务。"
        request["delivery"] = {"commit": True, "push": True, "draft_pr": True}
        restarted_manager = LocalTaskManager(
            self.fixture.store,
            self.fixture.runtime,
            readiness_provider=healthy,
            clock=lambda: self.now,
        )
        created = restarted_manager.create(confirmation)
        self.assertEqual(response["plan"]["canonical_goal"], goal)
        self.assertEqual(created["task"]["goal"], goal)
        self.assertEqual(created["task"]["delivery"], {
            "commit": False,
            "push": False,
            "draft_pr": False,
        })

    def test_expired_hash_mismatch_and_superseded_plans_fail_closed(self) -> None:
        request = self.request()
        _, expired = self.planned(request)
        self.now += timedelta(minutes=11)
        with self.assertRaises(StateConflictError) as raised:
            self.manager.create(expired)
        self.assertEqual(raised.exception.error_code, "local_task_plan_expired")

        self.now -= timedelta(minutes=11)
        _, mismatch = self.planned(request)
        mismatch["expected_plan_hash"] = "0" * 64
        with self.assertRaises(StateConflictError) as raised:
            self.manager.create(mismatch)
        self.assertEqual(raised.exception.error_code, "local_task_plan_hash_mismatch")

        _, superseded = self.planned(request)
        self.planned({**request, "goal": "Review the newer canonical request and report findings."})
        with self.assertRaises(StateConflictError) as raised:
            self.manager.create(superseded)
        self.assertEqual(raised.exception.error_code, "local_task_plan_superseded")
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_profile_and_readiness_changes_reject_old_plan(self) -> None:
        readiness = MutableReadiness()
        manager = LocalTaskManager(
            self.fixture.store,
            self.fixture.runtime,
            readiness_provider=readiness,
            clock=lambda: self.now,
        )
        request = self.request()
        _, confirmation = self.planned(request, manager)
        readiness.ready = False
        with self.assertRaises(StateConflictError):
            manager.create(confirmation)

        readiness.ready = True
        _, confirmation = self.planned(request, manager)
        project = self.fixture.store.get_project("project-one")
        project["verification_commands"] = [
            {
                "id": "new-check",
                "text": "new check",
                "command": [sys.executable, "-c", "pass"],
                "always_run": True,
            }
        ]
        self.fixture.store.register_project(project)
        with self.assertRaises(StateConflictError):
            manager.create(confirmation)

    def test_delivery_can_tighten_but_never_expand_project_policy(self) -> None:
        with self.assertRaises(InvalidTaskError):
            self.manager.plan(
                self.request(
                    "implement",
                    delivery={"commit": True, "push": True, "draft_pr": False},
                )
            )
        with self.assertRaises(InvalidTaskError):
            self.manager.plan(
                self.request(
                    "analysis",
                    delivery={"commit": True, "push": False, "draft_pr": False},
                )
            )

    def test_concurrent_confirmation_creates_exactly_one_task(self) -> None:
        request = self.request()
        _, confirmation = self.planned(request)
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[Exception] = []

        def create() -> None:
            try:
                barrier.wait()
                results.append(self.manager.create(confirmation))
            except Exception as exc:  # pragma: no cover - diagnostic capture
                errors.append(exc)

        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "created")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], StateConflictError)
        self.assertEqual(errors[0].error_code, "local_task_plan_consumed")
        self.assertEqual(len(self.fixture.store.list_tasks()), 1)
        task = self.fixture.store.list_tasks()[0]
        self.assertEqual(task["source_type"], "local_app")
        self.assertEqual(task["local_task_type"], "analysis")
        self.assertEqual(task["project_config_sha256"], self.project["config_sha256"])

    def test_repeated_confirmation_fails_closed(self) -> None:
        _, confirmation = self.planned(self.request())
        self.assertEqual(self.manager.create(confirmation)["status"], "created")
        with self.assertRaises(StateConflictError) as raised:
            self.manager.create(confirmation)
        self.assertEqual(raised.exception.error_code, "local_task_plan_consumed")
        self.assertFalse(raised.exception.retryable)

    def test_create_transaction_rolls_back_task_and_plan_consumption(self) -> None:
        _, confirmation = self.planned(self.request())
        with patch.object(
            TaskStore, "_insert_task_record", side_effect=RuntimeError("injected")
        ), self.assertRaises(RuntimeError):
            self.manager.create(confirmation)
        with self.fixture.store.connect() as connection:
            row = connection.execute("SELECT consumed_at, task_id FROM local_task_plans").fetchone()
        self.assertIsNone(row["consumed_at"])
        self.assertIsNone(row["task_id"])
        self.assertEqual(self.fixture.store.list_tasks(), [])
        self.assertEqual(self.manager.create(confirmation)["status"], "created")

    def test_transaction_rejects_tampered_persisted_plan_document(self) -> None:
        _, confirmation = self.planned(self.request())
        token_sha256 = sha256(confirmation["plan_token"].encode("utf-8")).hexdigest()
        with self.fixture.store.connect() as connection:
            row = connection.execute(
                "SELECT plan_json FROM local_task_plans WHERE plan_token_sha256 = ?",
                (token_sha256,),
            ).fetchone()
            plan = json.loads(row["plan_json"])
            plan["canonical_goal"] = "Tampered persisted goal must never be created."
            connection.execute(
                "UPDATE local_task_plans SET plan_json = ? WHERE plan_token_sha256 = ?",
                (_canonical_json(plan), token_sha256),
            )
        with self.assertRaises(StateConflictError) as raised:
            self.manager.create(confirmation)
        self.assertEqual(raised.exception.error_code, "local_task_plan_snapshot_invalid")
        self.assertEqual(self.fixture.store.list_tasks(), [])

    def test_analyze_no_changes_completes_with_persisted_result(self) -> None:
        analyzer = executable_script(
            self.fixture.root / "analyzer.py",
            "import sys\n_ = sys.stdin.read()\nprint('Finding: repository is ready')\n",
        )
        project = self.fixture.store.get_project("project-one")
        project["codex_command"] = [sys.executable, str(analyzer)]
        self.fixture.store.register_project(project)
        _, confirmation = self.planned(self.request())
        created = self.manager.create(confirmation)["task"]
        main_before = git(
            self.repo, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.COMPLETED.value)
        task = self.fixture.store.get_task(created["task_id"])
        self.assertEqual(task["result"]["kind"], "analysis")
        self.assertIn("repository is ready", task["result"]["summary"])
        self.assertIsNone(task["commit"])
        self.assertIsNone(task["pr_url"])
        self.assertEqual(
            git(self.repo, "status", "--porcelain=v1", "--untracked-files=all").stdout,
            main_before,
        )

    def test_implement_uses_isolated_worktree_and_stops_at_review(self) -> None:
        implementer = executable_script(
            self.fixture.root / "implementer.py",
            "from pathlib import Path\nimport sys\n_ = sys.stdin.read()\nPath('local-change.txt').write_text('done\\n')\nprint('implemented')\n",
        )
        project = self.fixture.store.get_project("project-one")
        project["codex_command"] = [sys.executable, str(implementer)]
        self.fixture.store.register_project(project)
        request = self.request("implement")
        _, confirmation = self.planned(request)
        created = self.manager.create(confirmation)["task"]
        main_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        result = TaskEngine(self.fixture.store, self.fixture.runtime).apply_once()
        self.assertEqual(result["status"], TaskStatus.AWAITING_REVIEW.value)
        task = self.fixture.store.get_task(created["task_id"])
        self.assertEqual(task["result"]["kind"], "implementation")
        self.assertEqual(task["result"]["changed_files"], ["local-change.txt"])
        self.assertTrue(task["commit"])
        self.assertIsNone(task["pr_url"])
        self.assertNotEqual(Path(task["worktree_path"]).resolve(), self.repo.resolve())
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), main_head)
        self.assertFalse((self.repo / "local-change.txt").exists())


if __name__ == "__main__":
    unittest.main()
