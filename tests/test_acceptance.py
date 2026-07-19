from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.acceptance import (
    ACCEPTANCE_CONTRACT_VERSION,
    ExternalAcceptanceManager,
    challenge_sha256,
)
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

    def test_challenge_plaintext_is_returned_once_and_only_hash_is_persisted(
        self,
    ) -> None:
        created = self.create()
        challenge = created["challenge"]
        with self.fixture.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_acceptance_runs WHERE run_id = ?",
                (created["run"]["run_id"],),
            ).fetchone()
        self.assertEqual(row["challenge_sha256"], challenge_sha256(challenge))
        self.assertNotIn(challenge, json.dumps(created["run"]))
        self.assertNotIn(
            challenge,
            self.fixture.runtime.database.read_bytes().decode(errors="ignore"),
        )
        self.assertEqual(created["run"]["core_version"], "0.8.0")
        self.assertEqual(created["run"]["app_version"], "0.7.0")
        self.assertEqual(
            created["run"]["acceptance_contract_version"],
            ACCEPTANCE_CONTRACT_VERSION,
        )
        self.assertEqual(created["run"]["tunnel_fingerprint"], TUNNEL_FINGERPRINT)

    def test_mismatch_never_changes_waiting_run(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        with self.assertRaisesRegex(InvalidTaskError, "did not match"):
            self.manager._complete_from_mcp_ingress("wrong_" + "z" * 32)
        self.assertEqual(
            self.manager.status()["current"]["status"], "waiting_for_chatgpt"
        )

    def test_expired_challenge_cannot_pass(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        self.clock.value += timedelta(minutes=11)
        with self.assertRaisesRegex(StateConflictError, "expired"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(self.manager.status()["current"]["status"], "expired")

    def test_replay_is_rejected_and_historical_transport_probe_survives_new_run(
        self,
    ) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        passed = self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(passed["status"], "mcp_transport_probe_passed")
        self.assertEqual(passed["ingress"], "local_or_tunneled_mcp_unattributed")
        with self.assertRaisesRegex(StateConflictError, "already used"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        replacement = self.create()
        status = self.manager.status()
        self.assertEqual(status["current"]["run_id"], replacement["run"]["run_id"])
        self.assertEqual(status["current"]["status"], "challenge_ready")
        self.assertEqual(status["last_transport_probe"]["run_id"], passed["run_id"])
        self.assertEqual(status["external_chatgpt_verification"]["status"], "pending")
        self.assertIsNone(status["applicable_external_chatgpt_verification"])

    def test_concurrent_duplicate_ingress_has_exactly_one_winner(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])

        def invoke() -> str:
            try:
                return self.manager._complete_from_mcp_ingress(created["challenge"])[
                    "status"
                ]
            except StateConflictError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: invoke(), range(2)))
        self.assertCountEqual(results, ["mcp_transport_probe_passed", "rejected"])
        current = self.manager.status()["current"]
        self.assertEqual(current["probe_count"], 1)
        self.assertEqual(
            [
                event["event_type"]
                for event in self.manager.list_events(current["run_id"])
            ].count("mcp_transport_probe_recorded"),
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

    def test_completion_fails_closed_when_installation_identity_changed(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        with sqlite3.connect(self.fixture.runtime.database) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "UPDATE installation_identity SET installation_id = ? WHERE singleton = 1",
                ("replacement-installation",),
            )
            connection.commit()
        with self.assertRaisesRegex(StateConflictError, "installation contract"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(
            self.manager.status()["current"]["status"], "waiting_for_chatgpt"
        )

    def test_completion_fails_closed_when_acceptance_contract_changed(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        with self.fixture.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE external_acceptance_runs SET acceptance_contract_version = ? "
                "WHERE run_id = ?",
                (ACCEPTANCE_CONTRACT_VERSION - 1, created["run"]["run_id"]),
            )
        with self.assertRaisesRegex(StateConflictError, "installation contract"):
            self.manager._complete_from_mcp_ingress(created["challenge"])
        self.assertEqual(
            self.manager.status()["current"]["status"], "waiting_for_chatgpt"
        )

    def test_restart_recovers_waiting_state_without_recovering_plaintext(self) -> None:
        created = self.create()
        self.manager.mark_waiting(created["run"]["run_id"])
        reopened = ExternalAcceptanceManager(self.fixture.store, now=self.clock)
        status = reopened.status()
        self.assertEqual(status["current"]["status"], "waiting_for_chatgpt")
        self.assertNotIn("challenge", status["current"])
        self.assertEqual(
            status["installation_fingerprint"],
            status["current"]["installation_fingerprint"],
        )

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
        self.repo, self.remote = create_remote_clone(
            self.fixture.root, "acceptance-target"
        )
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

    def test_unattributed_transport_probe_cannot_plan_real_project_task(self) -> None:
        with self.assertRaisesRegex(
            StateConflictError,
            "Trusted ChatGPT control-plane attestation is unavailable",
        ):
            acceptance_task_plan(self.fixture.store, "project-one")

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

    def test_create_is_also_locked_without_a_trusted_attestation_plan(self) -> None:
        with self.assertRaisesRegex(
            StateConflictError,
            "Trusted ChatGPT control-plane attestation is unavailable",
        ):
            create_acceptance_task(
                self.fixture.store,
                project_id="project-one",
                plan_token="forged-plan-token",
            )


if __name__ == "__main__":
    unittest.main()
