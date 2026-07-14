#!/usr/bin/env python3
"""Project Brain Gmail compatibility entrypoint.

Gmail ownership ends after canonical tasks are inserted into TaskStore. The
Core engine then claims at most one task under the shared runtime lock.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = SCRIPT_DIR.parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from project_brain.engine import TaskEngine
from project_brain.errors import AlreadyRunningError, ProjectBrainError
from project_brain.gmail import GmailAdapter
from project_brain.locking import RuntimeLock
from project_brain.projects import ProjectRegistry
from project_brain.runtime import RuntimePaths
from project_brain.store import TaskStore

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as exc:  # pragma: no cover - exercised by deployment environments
    raise SystemExit(
        "Gmail dependencies are missing; install experiments/gmail-inbox/requirements.txt"
    ) from exc

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_QUERY = 'is:unread newer_than:30d'
DEFAULT_ALLOWED_SENDER = ""


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?s)<[^>]+>", "\n", value)
    value = html.unescape(value)
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def extract_body(payload: dict[str, Any]) -> str:
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        data = (part.get("body") or {}).get("data")
        if data:
            decoded = decode_base64url(data)
            if part.get("mimeType") == "text/plain":
                plain.append(decoded)
            elif part.get("mimeType") == "text/html":
                html_parts.append(decoded)
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n\n".join(item.strip() for item in plain if item.strip()).strip()
    if html_parts:
        return "\n\n".join(strip_html(item) for item in html_parts if item.strip()).strip()
    data = (payload.get("body") or {}).get("data")
    value = decode_base64url(data)
    return strip_html(value) if payload.get("mimeType") == "text/html" else value.strip()


def load_credentials(runtime: RuntimePaths) -> Credentials:
    credentials_path = Path(
        os.environ.get("PB_GMAIL_CREDENTIALS", runtime.config_dir / "credentials.json")
    ).expanduser()
    token_path = Path(
        os.environ.get("PB_GMAIL_TOKEN", runtime.config_dir / "token.json")
    ).expanduser()
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise ProjectBrainError(f"Missing Gmail OAuth credentials: {credentials_path}")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def read_messages(
    runtime: RuntimePaths,
    *,
    query: str,
    max_results: int,
    allowed_sender: str,
) -> list[dict[str, Any]]:
    service = build(
        "gmail", "v1", credentials=load_credentials(runtime), cache_discovery=False
    )
    response = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    messages: list[dict[str, Any]] = []
    for item in response.get("messages") or []:
        message = service.users().messages().get(
            userId="me", id=item["id"], format="full"
        ).execute()
        payload = message.get("payload") or {}
        headers = {
            str(header.get("name", "")).lower(): decode_header_value(header.get("value"))
            for header in payload.get("headers") or []
        }
        _, sender = parseaddr(headers.get("from", ""))
        subject = html.unescape(headers.get("subject", ""))
        if sender.lower() != allowed_sender.lower():
            continue
        if not subject.startswith("[Project Brain"):
            continue
        messages.append(
            {
                "message_id": message["id"],
                "subject": subject,
                "body": extract_body(payload),
            }
        )
    return messages


def prepare_registry(
    store: TaskStore,
    runtime: RuntimePaths,
    *,
    config: Path | None,
    legacy_config: Path | None,
) -> None:
    registry = ProjectRegistry(store, runtime)
    if legacy_config:
        registry.import_bridge_v2(legacy_config)
    elif config:
        registry.load_config(config)
    elif runtime.config_file.exists():
        registry.load_config(runtime.config_file)
    elif not store.list_projects() and (SCRIPT_DIR / "bridge-config.json").exists():
        # Compatibility import is read-only; legacy JSON state is intentionally
        # left untouched for rollback.
        registry.import_bridge_v2(SCRIPT_DIR / "bridge-config.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project Brain Gmail input adapter")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--legacy-config", type=Path)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-results", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = RuntimePaths.from_value(args.runtime_root).ensure()
    store = TaskStore(runtime.database)
    store.initialize()
    try:
        with RuntimeLock(runtime.lock_file):
            prepare_registry(
                store,
                runtime,
                config=args.config,
                legacy_config=args.legacy_config,
            )
            allowed_sender = os.environ.get("PB_ALLOWED_SENDER", DEFAULT_ALLOWED_SENDER)
            if not allowed_sender:
                raise ProjectBrainError("PB_ALLOWED_SENDER is required")
            messages = read_messages(
                runtime,
                query=args.query,
                max_results=max(1, min(args.max_results, 100)),
                allowed_sender=allowed_sender,
            )
            adapter = GmailAdapter(store)
            imports = (
                adapter.import_messages(messages)
                if args.apply
                else adapter.preview_messages(messages)
            )
            execution = (
                TaskEngine(store, runtime).apply_once()
                if args.apply
                else {"status": "dry_run", "task": None}
            )
            print(
                json.dumps(
                    {
                        "mode": "apply" if args.apply else "dry_run",
                        "imported_count": sum(bool(item.get("created")) for item in imports),
                        "messages": imports,
                        "execution": execution,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except AlreadyRunningError:
        print(json.dumps({"status": "already_running"}))
        return 0
    except (ProjectBrainError, HttpError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_category": getattr(exc, "category", "gmail_api"),
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
