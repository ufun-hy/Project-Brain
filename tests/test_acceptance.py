from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.acceptance import ExternalAcceptanceManager, challenge_sha256
from project_brain.acceptance_tasks import (
    ACCEPTANCE_DOCUMENT_PATH,
    acceptance_task_plan,
    create_acceptance_task,
)
from project_brain.errors import InvalidTaskError, StateConflictError
from project_brain.engine import TaskEngine
from project_brain.git_history import GitHistoryNormalizer
from project_brain.ingress import TaskImporter
from project_brain.models import CanonicalTask
from project_brain.verification import VerificationRunner

from tests.helpers import CoreFixture, create_remote_clone, git


TUNNEL_FINGERPRINT = "a" * 64


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


class TokenSequence:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"challenge_{self.index:02d}_" + "x" * 32


class ExternalAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.clock = MutableClock()
        self.tokens = TokenSequence()
        self.manager = ExternalAcceptanceManager(
            self.fixture.store,
            now=self.clock,
            token_factory=self.tokens,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def create(self) -> dict:
        return self.manager.create_challenge(
            app_version="0.7.0",
            tunnel_fingerprint=TUNNEL_FINGERPRINT,
        )

    def test_challenge_plaintext_is_returned_once_and_only_hash_is_persisted(self) -> None:
        created = self.create()
        challenge = created["challenge"]
        with self.fixture.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_acceptance_runs WHERE run_id = ?",
                (created["run"]["run_id"],),
            ).fetchone()
        self.assertEqual(row["challenge_sha256"], challenge_sha256(challenge))
        self.assertNotIn(challenge, json.dumps(created["run"]))
        self.assertNotIn(challenge, self.fixture.runtime.database.read_bytes().decode(errors="ignore"))
        self.assertEqual(created["run"]["core_version"], "0.7.0")
        self.assertEqual(created["run"]["app_version"], "0.7.0")
        self.assertEqual(created["run"]["tunnel_fingerprint"], TUNNEL_FINGERPRINT)

    def test_mismatch_never_changes_waiting_run(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        with self.assertRaisesRegex(InvalidTaskError, "did not match"):
            self.manager._complete_from_mcp_ingress("wrong_" + "z" * 32)
        self.assertEqual(self.manager.status()["current"]["status"], "waiting_for_chatgpt")

    def test_expired_challenge_cannot_pass(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        self.clock.value += timedelta(minutes=11)
        with self.assertRaisesRegex(StateConflictError, "expired"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(self.manager.status()["current"]["status"], "expired")

    def test_replay_is_rejected_and_historical_pass_survives_new_current_run(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        passed = self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(passed["ingress"], "mcp_streamable_http")
        with self.assertRaisesRegex(StateConflictError, "already used"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        replacement = self.create()
        status = self.manager.status()
        self.assertEqual(status["current"]["run_id"], replacement["run"]["run_id"])
        self.assertEqual(status["current"]["status"], "challenge_ready")
        self.assertEqual(status["last_passed"]["run_id"], passed["run_id"])

    def test_concurrent_duplicate_ingress_has_exactly_one_winner(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])

        def invoke() -> str:
            try:
                return self.manager._complete_from_mcp_ingress(created["challenge"])["status"]
            except StateConflictError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: invoke(), range(2)))
        self.assertCountEqual(results, ["passed", "rejected"])
        current = self.manager.status()["current"]
        self.assertEqual(current["probe_count"], 1)
        self.assertEqual(
            [event["event_type"] for event in self.manager.list_events(current["run_id"])].count(
                "acceptance_probe_passed"
            ),
            1,
        )

    def test_new_challenge_supersedes_unfinished_run(self) -> None:
        first = self.create()
        self.manager.mark_waiting(first["run"]["run_id"])
        second = self.create()
        with self.fixture.store.connect() as connection:
            old = connection.execute(
                "SELECT status FROM external_acceptance_runs WHERE run_id = ?",
                (first["run"]["run_id"],),
            ).fetchone()
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(second["run"]["status"], "challenge_ready")

    def test_restart_recovers_waiting_state_without_recovering_plaintext(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        reopened = ExternalAcceptanceManager(self.fixture.store, now=self.clock)
        status = reopened.status()
        self.assertEqual(status["current"]["status"], "waiting_for_chatgpt")
        self.assertNotIn("challenge", status["current"])
        self.assertEqual(status["installation_fingerprint"], status["current"]["installation_fingerprint"])

    def test_events_contain_no_challenge_plaintext_or_hash(self) -> None:
        created = self.create()
        events = self.manager.list_events(created["run"]["run_id"])
        rendered = json.dumps(events)
        self.assertNotIn(created["challenge"], rendered)
        self.assertNotIn(challenge_sha256(created["challenge"]), rendered)
        self.assertNotIn("challenge_sha256", rendered)

    def test_reset_is_failed_not_passed_and_pass_requires_waiting(self) -> None:
        created = self.create()
        with self.assertRaisesRegex(StateConflictError, "not waiting"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        reset = self.manager.reset(created["run"]["run_id"])
        self.assertEqual(reset["status"], "failed")
        self.assertEqual(reset["failure_code"], "operator_reset")


class AcceptanceTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "acceptance-target")
        self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            auto_push=True,
            auto_pr=True,
        )
        manager = ExternalAcceptanceManager(
            self.fixture.store,
            token_factory=lambda: "acceptance_task_" + "q" * 32,
        )
        created = manager.create_challenge(
            app_version="0.7.0", tunnel_fingerprint=TUNNEL_FINGERPRINT
        )
        manager.mark_waiting(created["run"]["run_id"])
        manager._complete_from_mcp_ingress(created["challenge"])

    def tearDown(self) -> None:
        self.fixture.close()

    def test_plan_and_create_are_bound_to_passed_run_project_snapshot_and_fixed_file(self) -> None:
        plan = acceptance_task_plan(self.fixture.store, "project-one")
        task, created, applied = create_acceptance_task(
            self.fixture.store,
            project_id="project-one",
            plan_token=plan["plan_token"],
        )
        self.assertTrue(created)
        self.assertEqual(applied, plan)
        self.assertEqual(task["source_type"], "product_shell_acceptance")
        self.assertEqual(task["task_type"], "codex")
        self.assertEqual(plan["changed_files"], [ACCEPTANCE_DOCUMENT_PATH])
        self.assertEqual(task["payload"]["acceptance_document_path"], ACCEPTANCE_DOCUMENT_PATH)
        self.assertNotIn("command", task["payload"])
        self.assertNotIn("argv", task["payload"])

    def test_public_importer_cannot_forge_reserved_acceptance_source(self) -> None:
        with self.assertRaisesRegex(InvalidTaskError, "Reserved"):
            TaskImporter(self.fixture.store).import_value(
                CanonicalTask(
                    task_id="forged-acceptance",
                    project_id="project-one",
                    dedupe_key="forged-acceptance",
                    revision=1,
                    source_type="product_shell_acceptance",
                    goal="forge",
                    payload={"prompt": "forge"},
                ).as_record()
            )

    def test_fixed_verifier_accepts_exact_document_and_rejects_extra_change(self) -> None:
        plan = acceptance_task_plan(self.fixture.store, "project-one")
        task, _, _ = create_acceptance_task(
            self.fixture.store,
            project_id="project-one",
            plan_token=plan["plan_token"],
        )
        base = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        target = self.repo / ACCEPTANCE_DOCUMENT_PATH
        target.parent.mkdir(parents=True)
        target.write_text(task["payload"]["acceptance_document_content"], encoding="utf-8")
        git(self.repo, "add", ACCEPTANCE_DOCUMENT_PATH)
        git(self.repo, "commit", "-m", "acceptance")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        candidate = {**task, "base_sha": base, "head_sha": head, "commit": head}
        result = VerificationRunner(self.fixture.store, self.fixture.runtime)._verify_acceptance_document(
            candidate, self.repo
        )
        self.assertEqual(result["status"], "passed")

        (self.repo / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        git(self.repo, "add", "unexpected.txt")
        git(self.repo, "commit", "-m", "unexpected")
        extra_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        failed = VerificationRunner(
            self.fixture.store, self.fixture.runtime
        )._verify_acceptance_document(
            {**candidate, "head_sha": extra_head, "commit": extra_head}, self.repo
        )
        self.assertEqual(failed["status"], "failed")

    def test_fixed_task_runs_through_isolated_pipeline_and_stops_at_draft_review(self) -> None:
        plan = acceptance_task_plan(self.fixture.store, "project-one")
        task, _, _ = create_acceptance_task(
            self.fixture.store,
            project_id="project-one",
            plan_token=plan["plan_token"],
        )

        class FixedAcceptanceCodex:
            def execute(inner_self, *, task, worktree, snapshot, **_):
                target = Path(worktree) / ACCEPTANCE_DOCUMENT_PATH
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    task["payload"]["acceptance_document_content"], encoding="utf-8"
                )
                return GitHistoryNormalizer().normalize(
                    worktree, snapshot, message="docs: record Project Brain acceptance"
                )

        class DraftOnlyPublisher:
            def publish(inner_self, **_):
                return {
                    "pushed": False,
                    "pr_url": "https://example.test/project/pull/1",
                }

        result = TaskEngine(
            self.fixture.store,
            self.fixture.runtime,
            codex=FixedAcceptanceCodex(),
            github=DraftOnlyPublisher(),
        ).apply_once()
        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(result["task"]["task_id"], task["task_id"])
        self.assertEqual(result["task"]["pr_url"], "https://example.test/project/pull/1")
        self.assertEqual(result["task"]["branch"].startswith("brain/"), True)
        self.assertEqual(result["task"]["head_sha"], result["task"]["commit"])
        self.assertEqual(result["evidence"][0]["status"], "passed")
        self.assertEqual(result["evidence"][0]["criterion_id"], "rc1-acceptance-document")
        changed = git(
            Path(result["task"]["worktree_path"]),
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            result["task"]["commit"],
        ).stdout.splitlines()
        self.assertEqual(changed, [ACCEPTANCE_DOCUMENT_PATH])


if __name__ == "__main__":
    unittest.main()
