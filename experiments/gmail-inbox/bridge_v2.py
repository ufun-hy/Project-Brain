#!/usr/bin/env python3
"""
Project Brain Bridge v2

End-to-end:
Gmail task -> validate -> project allowlist -> branch -> action
-> commit -> push -> draft PR -> local result state.

Supported task types:
- write_files
- codex
- command

Security:
- Gmail read-only OAuth
- trusted sender allowlist
- registered repositories only
- no path traversal
- never write directly to protected branch
- command tasks use named allowlisted commands only
- Codex runs in the selected registered repository
- duplicate Gmail message IDs are ignored
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from gmail_callback import GmailCallback
from task_status import StatusStore, heartbeat, new_record, transition, write_report

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
SCRIPT_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = SCRIPT_DIR / "credentials.json"
TOKEN_PATH = SCRIPT_DIR / "token.json"
CONFIG_PATH = SCRIPT_DIR / "bridge-config.json"
STATE_PATH = SCRIPT_DIR / "processed.json"
RESULTS_DIR = SCRIPT_DIR / "results"
FAILURES_PATH = SCRIPT_DIR / "failures.json"

DEFAULT_QUERY = 'is:unread from:hy404051@gmail.com newer_than:30d'
DEFAULT_ALLOWED_SENDER = "hy404051@gmail.com"
PROTECTED_BRANCHES = {"main", "master"}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_CODEX_COMMAND = ["codex", "exec", "--sandbox", "workspace-write", "-"]


class BridgeError(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=check,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BridgeError(f"Command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(f"Command timed out: {' '.join(args)}") from exc
    except subprocess.CalledProcessError as exc:
        raise BridgeError(
            f"Command failed ({exc.returncode}): {' '.join(args)}\n"
            f"{exc.stderr or exc.stdout}"
        ) from exc


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], check=check)


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
        return "\n\n".join(x.strip() for x in plain if x.strip()).strip()
    if html_parts:
        return "\n\n".join(strip_html(x) for x in html_parts if x.strip()).strip()
    data = (payload.get("body") or {}).get("data")
    if not data:
        return ""
    value = decode_base64url(data)
    return strip_html(value) if payload.get("mimeType") == "text/html" else value.strip()


def headers(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name", "")).lower()
        if name:
            result[name] = decode_header_value(item.get("value"))
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
                raise BridgeError(f"Missing {CREDENTIALS_PATH}")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise BridgeError(f"Missing file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Invalid JSON in {path}: {exc}") from exc


def save_json(path: Path, value: Any) -> None:
    from task_status import atomic_json
    atomic_json(path, value)


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    if not isinstance(config.get("projects"), dict):
        raise BridgeError("bridge-config.json requires a projects object")
    return config


def safe_relative_path(value: str) -> Path:
    p = Path(value)
    if p.is_absolute() or not p.parts:
        raise BridgeError(f"Invalid relative path: {value}")
    if any(part in {"", ".", ".."} for part in p.parts):
        raise BridgeError(f"Path traversal is forbidden: {value}")
    if p.parts[0] == ".git":
        raise BridgeError("Writing inside .git is forbidden")
    return p


def resolve_project(config: dict[str, Any], name: str) -> tuple[Path, dict[str, Any]]:
    project = config["projects"].get(name)
    if not project:
        raise BridgeError(f"Unregistered project: {name}")
    repo = Path(project["path"]).expanduser().resolve()
    if not (repo / ".git").exists():
        raise BridgeError(f"Not a Git repository: {repo}")
    return repo, project


def require_clean_repo(repo: Path) -> None:
    if git(repo, "status", "--porcelain").stdout.strip():
        raise BridgeError("Repository has uncommitted changes")


def current_branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current").stdout.strip()


def ensure_base(repo: Path, base: str) -> None:
    if base not in PROTECTED_BRANCHES:
        raise BridgeError(f"Configured base branch is not protected: {base}")
    git(repo, "checkout", base)
    git(repo, "pull", "--ff-only")


def local_branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def remote_branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "ls-remote", "--exit-code", "--heads", "origin", branch, check=False).returncode == 0


def pr_for_branch(repo: Path, branch: str) -> str | None:
    completed = run(
        ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "url", "--limit", "1"],
        cwd=repo,
        check=False,
    )
    if completed.returncode != 0:
        raise BridgeError(f"Unable to inspect pull requests for existing branch {branch}: {completed.stderr or completed.stdout}")
    try:
        prs = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Invalid GitHub response while inspecting branch {branch}") from exc
    return prs[0].get("url") if prs else None


def prepare_task_branch(repo: Path, branch: str, base: str) -> None:
    """Remove only an unchanged, unpushed deterministic branch from an interrupted run."""
    if not local_branch_exists(repo, branch):
        git(repo, "checkout", "-b", branch)
        return
    if remote_branch_exists(repo, branch):
        pr_url = pr_for_branch(repo, branch)
        detail = f" with existing PR {pr_url}" if pr_url else " on origin without a discoverable PR"
        raise BridgeError(f"Task branch {branch} already exists{detail}; inspect it before retrying")
    base_sha = git(repo, "rev-parse", base).stdout.strip()
    branch_sha = git(repo, "rev-parse", branch).stdout.strip()
    if branch_sha != base_sha:
        raise BridgeError(
            f"Local task branch {branch} contains commits and is not pushed; inspect or remove it before retrying"
        )
    git(repo, "branch", "-d", branch)
    git(repo, "checkout", "-b", branch)


def return_to_clean_base(repo: Path, base: str) -> None:
    git(repo, "checkout", base)
    require_clean_repo(repo)


def cleanup_failed_task(repo: Path, base: str, branch: str) -> None:
    if current_branch(repo) == branch:
        git(repo, "reset", "--hard")
        git(repo, "clean", "-fd")
        git(repo, "checkout", base)
    require_clean_repo(repo)
    if local_branch_exists(repo, branch):
        git(repo, "branch", "-D", branch)


def task_branch(message_id: str, task_type: str) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9-]", "-", message_id[-10:])
    return f"brain/{task_type}-{suffix}"


def read_messages(query: str, max_results: int, allowed_sender: str) -> list[dict[str, str]]:
    service = build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
    response = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    result: list[dict[str, str]] = []
    for item in response.get("messages") or []:
        message = service.users().messages().get(
            userId="me", id=item["id"], format="full"
        ).execute()
        payload = message.get("payload") or {}
        h = headers(payload)
        _, sender = parseaddr(h.get("from", ""))
        subject = html.unescape(h.get("subject", ""))

        if sender.lower() != allowed_sender.lower():
            continue
        if not subject.startswith("[Project Brain Task]"):
            continue

        result.append({
            "message_id": message["id"],
            "thread_id": message.get("threadId", ""),
            "sender": sender,
            "message_id_header": h.get("message-id", ""),
            "subject": subject,
            "body": extract_body(payload),
        })
    return result

def send_callback(message: dict[str, str], record: dict[str, Any]) -> None:
    service=build("gmail","v1",credentials=load_credentials(),cache_discovery=False)
    GmailCallback(service).send(message,record)


def parse_task(body: str) -> dict[str, Any]:
    normalized = html.unescape(body).strip()
    normalized = (
        normalized
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    try:
        task = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Task body must be JSON: {exc}") from exc

    if not isinstance(task, dict):
        raise BridgeError("Task body must be a JSON object")
    if task.get("type") not in {"write_files", "codex", "command"}:
        raise BridgeError("type must be write_files, codex, or command")
    if not isinstance(task.get("project"), str):
        raise BridgeError("project must be a string")
    return task


def write_files(repo: Path, task: dict[str, Any]) -> list[str]:
    files = task.get("files")
    if not isinstance(files, list) or not files:
        raise BridgeError("write_files task requires a non-empty files array")

    changed: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise BridgeError("Each files item must be an object")
        path = safe_relative_path(str(item.get("path", "")))
        content = item.get("content")
        if not isinstance(content, str):
            raise BridgeError(f"content must be a string for {path}")

        target = (repo / path).resolve()
        if repo != target and repo not in target.parents:
            raise BridgeError(f"Target escapes repository: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed.append(str(path))
    return changed


def run_codex(repo: Path, task: dict[str, Any], project_cfg: dict[str, Any], *, record=None, store=None, log_path=None) -> list[str]:
    prompt = task.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BridgeError("codex task requires prompt")

    codex_command = project_cfg.get("codex_command", DEFAULT_CODEX_COMMAND)
    if not isinstance(codex_command, list) or not all(isinstance(x, str) for x in codex_command):
        raise BridgeError("codex_command must be an array of strings")

    if record is not None:
        record["codex_attempt"] = int(record.get("codex_attempt", 0)) + 1
        heartbeat(record, "Codex process active"); store.save(record)
    if log_path: log_path.parent.mkdir(parents=True,exist_ok=True)
    output = open(log_path,"w+",encoding="utf-8") if log_path else tempfile.TemporaryFile(mode="w+",encoding="utf-8")
    with output:
        process = subprocess.Popen(codex_command,cwd=str(repo),text=True,stdin=subprocess.PIPE,stdout=output,stderr=subprocess.STDOUT)
        assert process.stdin is not None
        process.stdin.write(prompt); process.stdin.close(); process.stdin=None
        interval=max(5,int(project_cfg.get("heartbeat_interval_seconds",30))); timeout=int(project_cfg.get("codex_timeout_seconds",1800)); started=time.monotonic()
        while process.poll() is None:
            if time.monotonic()-started > timeout: process.kill(); raise BridgeError("Codex timed out")
            time.sleep(min(interval,1) if os.environ.get("PB_TEST_FAST_HEARTBEAT") else interval)
            if record is not None: heartbeat(record,"Codex process active"); store.save(record)
        output.seek(0); combined=output.read(); completed=subprocess.CompletedProcess(codex_command,process.returncode,combined,"")
    if record is not None:
        record["recent_log_tail"]=combined.splitlines()[-40:]; record["log_path"]=str(log_path) if log_path else None; store.save(record)
    if completed.returncode != 0:
        raise BridgeError(f"Codex failed:\n{completed.stderr or completed.stdout}")

    status = git(repo, "status", "--porcelain").stdout.splitlines()
    return [line[3:] if len(line) > 3 else line for line in status]


def run_named_command(repo: Path, task: dict[str, Any], project_cfg: dict[str, Any]) -> dict[str, Any]:
    command_name = task.get("command")
    allowed = project_cfg.get("allowed_commands", {})
    if not isinstance(command_name, str) or command_name not in allowed:
        raise BridgeError(f"Command is not allowlisted: {command_name}")
    argv = allowed[command_name]
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise BridgeError(f"Invalid allowed command definition: {command_name}")

    completed = run(argv, cwd=repo, timeout=int(project_cfg.get("command_timeout_seconds", 900)))
    return {
        "command": command_name,
        "stdout": completed.stdout[-5000:],
        "stderr": completed.stderr[-5000:],
    }


def commit_changes(repo: Path, message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise BridgeError("commit_message is required")
    git(repo, "add", "-A")
    quiet = git(repo, "diff", "--cached", "--quiet", check=False)
    if quiet.returncode == 0:
        raise BridgeError("Task produced no changes")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def push_branch(repo: Path, branch: str) -> None:
    git(repo, "push", "-u", "origin", branch)


def create_pr(repo: Path, branch: str, base: str, task: dict[str, Any]) -> str:
    title = task.get("pr_title") or task.get("commit_message") or f"Project Brain task: {branch}"
    body = task.get("pr_body") or (
        "## Project Brain execution handoff\n\n**Status: `awaiting_review` — not accepted.**\n\n"
        f"Source task type: `{task['type']}`"
    )
    completed = run(
        [
            "gh", "pr", "create",
            "--draft",
            "--base", base,
            "--head", branch,
            "--title", title,
            "--body", body,
        ],
        cwd=repo,
    )
    return completed.stdout.strip()


def process_task(
    message: dict[str, str],
    task: dict[str, Any],
    config: dict[str, Any],
    *,
    apply: bool,
    status_store: StatusStore | None = None,
    status_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo, project_cfg = resolve_project(config, task["project"])
    base = project_cfg.get("base_branch", "main")
    require_clean_repo(repo)

    result: dict[str, Any] = {
        "message_id": message["message_id"],
        "project": task["project"],
        "type": task["type"],
        "repo": str(repo),
        "mode": "apply" if apply else "dry_run",
    }
    if not apply:
        return result

    ensure_base(repo, base)
    branch = task_branch(message["message_id"], task["type"])
    prepare_task_branch(repo, branch, base)
    result["branch"] = branch
    if status_record is not None:
        status_record["branch"]=branch; transition(status_record,"running","Executing task",last_heartbeat_at=datetime.now(timezone.utc).isoformat()); status_store.save(status_record)

    try:
        if task["type"] == "write_files":
            result["changed_files"] = write_files(repo, task)
        elif task["type"] == "codex":
            result["changed_files"] = run_codex(repo, task, project_cfg,record=status_record,store=status_store,log_path=(status_store.root/"logs"/f"{message['message_id']}.log") if status_store else None)
        elif task["type"] == "command":
            result["command_result"] = run_named_command(repo, task, project_cfg)
        else:
            raise BridgeError("Unsupported task type")

        commit = commit_changes(repo, task.get("commit_message", "chore: project brain task"))
        result["commit"] = commit
        if status_record is not None: status_record.update(commit=commit,current_action="Commit created"); status_store.save(status_record)

        if project_cfg.get("auto_push", True):
            push_branch(repo, branch)
            result["pushed"] = True
        else:
            result["pushed"] = False

        if project_cfg.get("auto_pr", True) and result["pushed"]:
            result["pr_url"] = create_pr(repo, branch, base, task)

        return_to_clean_base(repo, base)
        if status_record is not None:
            transition(status_record,"awaiting_review","Draft PR ready for review",commit=result.get("commit"),pr_url=result.get("pr_url"),evidence_summary="Execution completed successfully; explicit review is required.",test_summary=(result.get("command_result") or {}).get("command","Not separately run")); status_store.save(status_record)
        return result

    except Exception:
        try:
            cleanup_failed_task(repo, base, branch)
        except Exception:
            pass
        raise


def failure_attempts(failures: dict[str, Any], message_id: str) -> int:
    record = failures.get(message_id, {})
    return int(record.get("attempt_count", 0)) if isinstance(record, dict) else 0


def record_failure(failures: dict[str, Any], message_id: str, error: Exception) -> dict[str, Any]:
    record = {
        "attempt_count": failure_attempts(failures, message_id) + 1,
        "last_error": str(error),
        "last_attempt_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    failures[message_id] = record
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-results", type=int, default=50)
    args = parser.parse_args()

    try:
        config = load_config()
        status_store = StatusStore()
        state = load_json(STATE_PATH, {"processed_message_ids": []})
        failures = load_json(FAILURES_PATH, {})
        if not isinstance(failures, dict):
            raise BridgeError("failures.json must contain an object")
        processed = set(state.get("processed_message_ids", []))
        max_attempts = int(config.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
        if max_attempts < 1:
            raise BridgeError("max_attempts must be at least 1")
        allowed_sender = os.environ.get("PB_ALLOWED_SENDER", DEFAULT_ALLOWED_SENDER)
        messages = read_messages(args.query, args.max_results, allowed_sender)

        results: list[dict[str, Any]] = []
        for message in messages:
            if message["message_id"] in processed:
                continue
            message_id = message["message_id"]
            attempts = failure_attempts(failures, message_id)
            if args.apply and attempts >= max_attempts:
                results.append({
                    "message_id": message_id,
                    "status": "retry_limit_reached",
                    "attempt_count": attempts,
                    "last_error": failures[message_id].get("last_error", ""),
                    "action_required": "Inspect failures.json and repository state, then remove this failure record to retry.",
                })
                continue
            try:
                task = parse_task(message["body"])
                record = new_record(message_id,task["project"],task.get("pr_title") or message["subject"],attempts+1)
                status_store.save(record)
                if args.apply: transition(record,"claimed","Bridge claimed task"); status_store.save(record)
                result = process_task(message, task, config, apply=args.apply,status_store=status_store,status_record=record)
                results.append(result)
            except (BridgeError, HttpError) as exc:
                if not args.apply:
                    raise
                record = record_failure(failures, message_id, exc)
                save_json(FAILURES_PATH, failures)
                results.append({
                    "message_id": message_id,
                    "status": "retry_pending" if record["attempt_count"] < max_attempts else "retry_limit_reached",
                    **record,
                    "action_required": "Human intervention required." if record["attempt_count"] >= max_attempts else None,
                })
                try:
                    live=status_store.load(message_id)
                    final="blocked" if record["attempt_count"] >= max_attempts else "failed"
                    transition(live,final,"Retry exhausted" if final=="blocked" else "Execution failed",error=str(exc),blocked_reason=str(exc) if final=="blocked" else None,evidence_summary=str(exc)); status_store.save(live)
                    write_report(status_store.root,message_id,{"task_id":message_id,"summary":str(exc),"state":final,"changed_files":[],"branch":live.get("branch"),"commit":live.get("commit"),"pr_url":live.get("pr_url"),"commands_tests":[],"acceptance_criteria":[],"known_gaps":[],"errors":[str(exc)],"started_at":live.get("started_at"),"finished_at":live.get("finished_at"),"bridge_attempt":live.get("bridge_attempt"),"codex_attempt":live.get("codex_attempt")})
                    try: send_callback(message,live)
                    except HttpError: pass
                except (OSError,ValueError): pass
                continue

            if args.apply:
                processed.add(message_id)
                failures.pop(message_id, None)
                state["processed_message_ids"] = sorted(processed)
                save_json(STATE_PATH, state)
                save_json(FAILURES_PATH, failures)
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                save_json(RESULTS_DIR / f"{message_id}.json", result)
                report={"task_id":message_id,"summary":"Execution complete; awaiting explicit review","state":"awaiting_review","changed_files":result.get("changed_files",[]),"branch":result.get("branch"),"commit":result.get("commit"),"pr_url":result.get("pr_url"),"commands_tests":([{"command":result["command_result"].get("command"),"exit_code":0}] if result.get("command_result") else []),"acceptance_criteria":task.get("acceptance_criteria",[]),"known_gaps":task.get("known_gaps",[]),"errors":[],"started_at":record.get("started_at"),"finished_at":record.get("updated_at"),"bridge_attempt":record.get("bridge_attempt"),"codex_attempt":record.get("codex_attempt")}
                write_report(status_store.root,message_id,report)
                try: send_callback(message,record)
                except HttpError as exc:
                    print(f"Gmail callback failed for {message_id}: {exc}",file=sys.stderr)

        print(json.dumps({
            "mode": "apply" if args.apply else "dry_run",
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, indent=2))
        return 0

    except (BridgeError, HttpError) as exc:
        print(f"Bridge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
