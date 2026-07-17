"""Durable one-time external acceptance challenges.

Challenge plaintext is returned once to the local Product Shell and is never
persisted. Completion is intentionally exposed only through the MCP adapter's
registered acceptance-probe tool.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import __version__
from .errors import InvalidTaskError, StateConflictError
from .models import parse_timestamp, validate_stable_id
from .store import TaskStore


ACTIVE_STATUSES = ("challenge_ready", "waiting_for_chatgpt")
TERMINAL_STATUSES = (
    "mcp_transport_probe_passed",
    "failed",
    "expired",
    "superseded",
)
DEFAULT_CHALLENGE_TTL_SECONDS = 600
CHALLENGE_BYTES = 32
ACCEPTANCE_CONTRACT_VERSION = 2
VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def challenge_sha256(challenge: str) -> str:
    return hashlib.sha256(challenge.encode("utf-8")).hexdigest()


def opaque_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ExternalAcceptanceManager:
    """Own challenge creation and durable state without exposing a pass setter."""

    def __init__(
        self,
        store: TaskStore,
        *,
        now: Callable[[], datetime] = _utc_now,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self._now = now
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(CHALLENGE_BYTES)
        )

    def create_challenge(
        self,
        *,
        app_version: str,
        tunnel_fingerprint: str,
        ttl_seconds: int = DEFAULT_CHALLENGE_TTL_SECONDS,
    ) -> dict[str, Any]:
        if not VERSION_PATTERN.fullmatch(app_version):
            raise InvalidTaskError("App version must be a bounded semantic version")
        if not FINGERPRINT_PATTERN.fullmatch(tunnel_fingerprint):
            raise InvalidTaskError("Tunnel fingerprint must be lowercase SHA-256")
        if isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 600:
            raise InvalidTaskError("Acceptance challenge TTL must be from 60 to 600 seconds")
        challenge = self._token_factory()
        if not isinstance(challenge, str) or not CHALLENGE_PATTERN.fullmatch(challenge):
            raise InvalidTaskError("Secure challenge generation returned an invalid value")
        digest = challenge_sha256(challenge)
        run_id = f"acceptance-{uuid.uuid4().hex}"
        created = self._now().astimezone(timezone.utc)
        expires = created + timedelta(seconds=ttl_seconds)
        with self.store.transaction(immediate=True) as connection:
            self._expire_locked(connection, created)
            installation = connection.execute(
                "SELECT installation_id FROM installation_identity WHERE singleton = 1"
            ).fetchone()
            if installation is None:
                raise StateConflictError("Project Brain installation identity is unavailable")
            active = connection.execute(
                "SELECT run_id, status FROM external_acceptance_runs "
                "WHERE status IN (?, ?) ORDER BY created_at",
                ACTIVE_STATUSES,
            ).fetchall()
            for row in active:
                connection.execute(
                    "UPDATE external_acceptance_runs SET status = 'superseded' "
                    "WHERE run_id = ? AND status = ?",
                    (row["run_id"], row["status"]),
                )
                self._event(
                    connection,
                    run_id=row["run_id"],
                    event_type="acceptance_superseded",
                    from_status=row["status"],
                    to_status="superseded",
                    payload={"replacement_run_id": run_id},
                    created_at=_iso(created),
                )
            connection.execute(
                """
                INSERT INTO external_acceptance_runs(
                    run_id, challenge_sha256, status, core_version, app_version,
                    acceptance_contract_version, installation_id,
                    tunnel_fingerprint, created_at, expires_at
                ) VALUES (?, ?, 'challenge_ready', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    digest,
                    __version__,
                    app_version,
                    ACCEPTANCE_CONTRACT_VERSION,
                    installation["installation_id"],
                    tunnel_fingerprint,
                    _iso(created),
                    _iso(expires),
                ),
            )
            self._event(
                connection,
                run_id=run_id,
                event_type="acceptance_challenge_created",
                from_status=None,
                to_status="challenge_ready",
                payload={"ttl_seconds": ttl_seconds},
                created_at=_iso(created),
            )
            row = connection.execute(
                "SELECT * FROM external_acceptance_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert row is not None
        return {
            "status": "challenge_ready",
            "challenge": challenge,
            "run": self._safe_run(row),
        }

    def mark_waiting(self, run_id: str) -> dict[str, Any]:
        validate_stable_id("acceptance run id", run_id)
        now = self._now().astimezone(timezone.utc)
        with self.store.transaction(immediate=True) as connection:
            self._expire_locked(connection, now)
            row = self._require_run(connection, run_id)
            if row["status"] == "waiting_for_chatgpt":
                return self._safe_run(row)
            if row["status"] != "challenge_ready":
                raise StateConflictError(
                    f"Acceptance run cannot start waiting from {row['status']}"
                )
            connection.execute(
                "UPDATE external_acceptance_runs SET status = 'waiting_for_chatgpt', "
                "waiting_at = ? WHERE run_id = ? AND status = 'challenge_ready'",
                (_iso(now), run_id),
            )
            self._event(
                connection,
                run_id=run_id,
                event_type="acceptance_waiting_started",
                from_status="challenge_ready",
                to_status="waiting_for_chatgpt",
                payload={},
                created_at=_iso(now),
            )
            updated = self._require_run(connection, run_id)
        return self._safe_run(updated)

    def reset(self, run_id: str) -> dict[str, Any]:
        validate_stable_id("acceptance run id", run_id)
        now = self._now().astimezone(timezone.utc)
        with self.store.transaction(immediate=True) as connection:
            self._expire_locked(connection, now)
            row = self._require_run(connection, run_id)
            if row["status"] not in ACTIVE_STATUSES:
                raise StateConflictError(
                    f"Acceptance run cannot be reset from {row['status']}"
                )
            connection.execute(
                "UPDATE external_acceptance_runs SET status = 'failed', "
                "failure_code = 'operator_reset' WHERE run_id = ? AND status = ?",
                (run_id, row["status"]),
            )
            self._event(
                connection,
                run_id=run_id,
                event_type="acceptance_reset",
                from_status=row["status"],
                to_status="failed",
                payload={"failure_code": "operator_reset"},
                created_at=_iso(now),
            )
            updated = self._require_run(connection, run_id)
        return self._safe_run(updated)

    def status(self) -> dict[str, Any]:
        now = self._now().astimezone(timezone.utc)
        with self.store.transaction(immediate=True) as connection:
            self._expire_locked(connection, now)
            current = connection.execute(
                "SELECT * FROM external_acceptance_runs "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            last_probe = connection.execute(
                "SELECT * FROM external_acceptance_runs "
                "WHERE status = 'mcp_transport_probe_passed' "
                "ORDER BY verified_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            installation = connection.execute(
                "SELECT installation_id, created_at FROM installation_identity WHERE singleton = 1"
            ).fetchone()
        return {
            "status": "ok",
            "current": self._safe_run(current) if current is not None else None,
            "last_transport_probe": (
                self._safe_run(last_probe) if last_probe is not None else None
            ),
            "external_chatgpt_verification": {
                "status": "pending",
                "reason_code": "trusted_control_plane_attestation_unavailable",
            },
            "applicable_external_chatgpt_verification": None,
            "core_version": __version__,
            "acceptance_contract_version": ACCEPTANCE_CONTRACT_VERSION,
            "installation_fingerprint": (
                opaque_fingerprint(installation["installation_id"])
                if installation is not None
                else None
            ),
        }

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        validate_stable_id("acceptance run id", run_id)
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM external_acceptance_events WHERE run_id = ? ORDER BY event_id",
                (run_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            result.append(value)
        return result

    def _complete_from_mcp_ingress(self, challenge: str) -> dict[str, Any]:
        """Complete one waiting run; this has no CLI or Swift adapter route."""
        if not isinstance(challenge, str) or not CHALLENGE_PATTERN.fullmatch(challenge):
            raise InvalidTaskError("Acceptance challenge format is invalid")
        digest = challenge_sha256(challenge)
        now = self._now().astimezone(timezone.utc)
        with self.store.transaction(immediate=True) as connection:
            self._expire_locked(connection, now)
            row = connection.execute(
                "SELECT * FROM external_acceptance_runs WHERE challenge_sha256 = ?",
                (digest,),
            ).fetchone()
            if row is None or not hmac.compare_digest(row["challenge_sha256"], digest):
                raise InvalidTaskError("Acceptance challenge did not match an active run")
            if row["status"] == "mcp_transport_probe_passed":
                raise StateConflictError("Acceptance challenge was already used")
            if row["status"] == "expired":
                raise StateConflictError("Acceptance challenge expired")
            if row["status"] != "waiting_for_chatgpt":
                raise StateConflictError(
                    f"Acceptance challenge is not waiting for ChatGPT: {row['status']}"
                )
            installation = connection.execute(
                "SELECT installation_id FROM installation_identity WHERE singleton = 1"
            ).fetchone()
            if (
                installation is None
                or row["installation_id"] != installation["installation_id"]
                or row["core_version"] != __version__
                or int(row["acceptance_contract_version"])
                != ACCEPTANCE_CONTRACT_VERSION
            ):
                raise StateConflictError(
                    "Acceptance challenge does not match the current Core installation contract"
                )
            cursor = connection.execute(
                "UPDATE external_acceptance_runs "
                "SET status = 'mcp_transport_probe_passed', verified_at = ?, "
                "ingress = 'local_or_tunneled_mcp_unattributed', "
                "probe_count = probe_count + 1 "
                "WHERE run_id = ? AND status = 'waiting_for_chatgpt'",
                (_iso(now), row["run_id"]),
            )
            if cursor.rowcount != 1:
                raise StateConflictError("Acceptance challenge was consumed concurrently")
            self._event(
                connection,
                run_id=row["run_id"],
                event_type="mcp_transport_probe_recorded",
                from_status="waiting_for_chatgpt",
                to_status="mcp_transport_probe_passed",
                payload={
                    "ingress": "local_or_tunneled_mcp_unattributed",
                    "external_chatgpt_verified": False,
                },
                created_at=_iso(now),
            )
            updated = self._require_run(connection, row["run_id"])
        return self._safe_run(updated)

    @staticmethod
    def _safe_run(row: Any) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "status": row["status"],
            "core_version": row["core_version"],
            "app_version": row["app_version"],
            "acceptance_contract_version": int(row["acceptance_contract_version"]),
            "installation_fingerprint": opaque_fingerprint(row["installation_id"]),
            "tunnel_fingerprint": row["tunnel_fingerprint"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "waiting_at": row["waiting_at"],
            "verified_at": row["verified_at"],
            "failure_code": row["failure_code"],
            "ingress": row["ingress"],
            "probe_count": int(row["probe_count"]),
        }

    @staticmethod
    def _require_run(connection: Any, run_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM external_acceptance_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise InvalidTaskError(f"Unknown acceptance run: {run_id}")
        return row

    def _expire_locked(self, connection: Any, now: datetime) -> None:
        rows = connection.execute(
            "SELECT run_id, status, expires_at FROM external_acceptance_runs "
            "WHERE status IN (?, ?)",
            ACTIVE_STATUSES,
        ).fetchall()
        for row in rows:
            expires = parse_timestamp(row["expires_at"])
            if expires is None or expires > now:
                continue
            connection.execute(
                "UPDATE external_acceptance_runs SET status = 'expired', "
                "failure_code = 'challenge_expired' WHERE run_id = ? AND status = ?",
                (row["run_id"], row["status"]),
            )
            self._event(
                connection,
                run_id=row["run_id"],
                event_type="acceptance_expired",
                from_status=row["status"],
                to_status="expired",
                payload={"failure_code": "challenge_expired"},
                created_at=_iso(now),
            )

    @staticmethod
    def _event(
        connection: Any,
        *,
        run_id: str | None,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO external_acceptance_events(
                run_id, event_type, from_status, to_status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, from_status, to_status, _json(payload), created_at),
        )
