#!/usr/bin/env python3
"""
Project Brain Gmail Inbox Experiment v0

Safety properties:
- Gmail read-only OAuth scope.
- Only reads unread messages with a Project Brain subject prefix.
- Only accepts messages from PB_ALLOWED_SENDER.
- Does not mark mail as read.
- Does not write files outside an optional JSON output path.
- Does not touch Git or invoke Codex.
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

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = Path(
    os.environ.get("PROJECT_BRAIN_RUNTIME_ROOT", "~/.project-brain")
).expanduser().resolve()
CONFIG_DIR = RUNTIME_ROOT / "config"
CREDENTIALS_PATH = Path(
    os.environ.get("PB_GMAIL_CREDENTIALS", CONFIG_DIR / "credentials.json")
).expanduser()
TOKEN_PATH = Path(
    os.environ.get("PB_GMAIL_TOKEN", CONFIG_DIR / "token.json")
).expanduser()

DEFAULT_QUERY = "is:unread newer_than:30d"
DEFAULT_ALLOWED_SENDER = ""


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


def decode_base64url(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data + padding)
    return raw.decode("utf-8", errors="replace")


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?s)<[^>]+>", "\n", value)
    value = html.unescape(value)
    lines = [line.strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def collect_bodies(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body_data = (part.get("body") or {}).get("data")
        if body_data:
            decoded = decode_base64url(body_data)
            if mime_type == "text/plain":
                plain.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)

        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return plain, html_parts


def extract_body(payload: dict[str, Any]) -> str:
    plain, html_parts = collect_bodies(payload)
    if plain:
        return "\n\n".join(part.strip() for part in plain if part.strip()).strip()
    if html_parts:
        return "\n\n".join(strip_html(part) for part in html_parts if part.strip()).strip()

    # Single-part messages can have data directly in payload.body.
    data = (payload.get("body") or {}).get("data")
    if data:
        value = decode_base64url(data)
        if payload.get("mimeType") == "text/html":
            return strip_html(value)
        return value.strip()
    return ""


def get_headers(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name", "")).lower()
        value = decode_header_value(item.get("value"))
        if name:
            result[name] = value
    return result


def load_credentials() -> Credentials:
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_PATH}. Download an OAuth Desktop app "
                    "credentials JSON file and save it with this name."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def read_messages(
    query: str,
    max_results: int,
    allowed_sender: str,
) -> list[dict[str, Any]]:
    creds = load_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    accepted: list[dict[str, Any]] = []
    allowed_sender = allowed_sender.strip().lower()

    for item in response.get("messages") or []:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        payload = message.get("payload") or {}
        headers = get_headers(payload)

        sender_name, sender_email = parseaddr(headers.get("from", ""))
        sender_email = sender_email.lower()

        if allowed_sender and sender_email != allowed_sender:
            print(
                f"Skipped message {message.get('id')}: sender {sender_email!r} "
                f"does not match PB_ALLOWED_SENDER.",
                file=sys.stderr,
            )
            continue

        subject = html.unescape(headers.get("subject", ""))
        if not subject.startswith("[Project Brain]"):
            print(
                f"Skipped message {message.get('id')}: unexpected subject.",
                file=sys.stderr,
            )
            continue

        accepted.append(
            {
                "message_id": message.get("id"),
                "thread_id": message.get("threadId"),
                "internal_date": message.get("internalDate"),
                "labels": message.get("labelIds") or [],
                "from": {
                    "name": sender_name,
                    "email": sender_email,
                },
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "subject": subject,
                "body": extract_body(payload),
            }
        )

    return accepted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Project Brain task messages from Gmail without acting."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once. Present for clarity; v0 always runs once.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Gmail search query. Default: {DEFAULT_QUERY}",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum messages to inspect. Default: 10",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optionally save the JSON result to this file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    allowed_sender = os.environ.get(
        "PB_ALLOWED_SENDER", DEFAULT_ALLOWED_SENDER
    )
    if not allowed_sender:
        print("Configuration error: PB_ALLOWED_SENDER is required", file=sys.stderr)
        return 2

    try:
        messages = read_messages(
            query=args.query,
            max_results=max(1, min(args.max_results, 100)),
            allowed_sender=allowed_sender,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except HttpError as error:
        print(f"Gmail API error: {error}", file=sys.stderr)
        return 3
    except Exception as error:
        print(f"Unexpected error: {type(error).__name__}: {error}", file=sys.stderr)
        return 4

    result = {
        "mode": "read_only",
        "query": args.query,
        "allowed_sender": allowed_sender,
        "count": len(messages),
        "messages": messages,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"\nSaved to: {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
