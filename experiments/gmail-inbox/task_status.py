"""Versioned task lifecycle, atomic local persistence, and structured audit reports."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATES = {"queued", "claimed", "running", "awaiting_review", "accepted", "needs_changes", "blocked", "failed", "cancelled"}
TRANSITIONS = {
    "queued": {"claimed", "cancelled", "blocked", "failed"},
    "claimed": {"running", "cancelled", "blocked", "failed"},
    "running": {"awaiting_review", "cancelled", "blocked", "failed"},
    "awaiting_review": {"accepted", "needs_changes"},
    "needs_changes": {"claimed", "cancelled"},
    "accepted": set(), "blocked": set(), "failed": set(), "cancelled": set(),
}
TERMINAL_STATES = {"accepted", "needs_changes", "blocked", "failed", "cancelled"}
MAX_TEXT = 5000

def bounded(value: Any, limit: int = MAX_TEXT) -> str:
    text = str(value or "")
    return text[-limit:]

def validate_record(record: dict[str, Any]) -> None:
    required = {"schema_version", "task_id", "gmail_message_id", "project", "title", "state",
                "current_action", "created_at", "updated_at", "attempt", "acceptance", "test_summary"}
    missing = sorted(required - record.keys())
    if missing: raise ValueError(f"Status record missing fields: {', '.join(missing)}")
    if record["schema_version"] != SCHEMA_VERSION: raise ValueError("Unsupported status schema version")
    if record["state"] not in STATES: raise ValueError(f"Invalid task state: {record['state']}")
    for key in ("task_id", "gmail_message_id", "project", "title", "current_action"):
        if not isinstance(record[key], str) or not record[key].strip(): raise ValueError(f"{key} must be non-empty")
    acceptance = record["acceptance"]
    if not isinstance(acceptance, dict) or not isinstance(acceptance.get("satisfied"), int):
        raise ValueError("acceptance.satisfied must be an integer")
    total = acceptance.get("total")
    if total is not None and (not isinstance(total, int) or total < acceptance["satisfied"] or acceptance["satisfied"] < 0):
        raise ValueError("acceptance total/satisfied is invalid")
    for key in ("error", "blocked_reason", "evidence_summary", "test_summary"):
        if record.get(key) is not None and len(str(record[key])) > MAX_TEXT: raise ValueError(f"{key} exceeds {MAX_TEXT} characters")

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def runtime_dir() -> Path:
    return Path(os.environ.get("PROJECT_BRAIN_RUNTIME_DIR", Path.home() / "Library/Application Support/ProjectBrain"))

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

class StatusStore:
    def __init__(self, root: Path | None = None): self.root = root or runtime_dir()
    def path(self, task_id: str) -> Path: return self.root / "tasks" / f"{task_id}.json"
    def save(self, record: dict[str, Any]) -> None: validate_record(record); atomic_json(self.path(record["task_id"]), record)
    def load(self, task_id: str) -> dict[str, Any]: return json.loads(self.path(task_id).read_text())
    def list(self) -> list[dict[str, Any]]:
        records=[]
        for path in (self.root / "tasks").glob("*.json") if (self.root / "tasks").exists() else []:
            try: records.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError): continue
        return sorted(records, key=lambda x: x.get("updated_at", ""), reverse=True)

def new_record(task_id: str, project: str, title: str, attempt: int = 1) -> dict[str, Any]:
    stamp=now()
    return {"schema_version":SCHEMA_VERSION,"task_id":task_id,"gmail_message_id":task_id,"project":project,"title":title,
      "state":"queued","current_action":"Task discovered","created_at":stamp,"started_at":None,"updated_at":stamp,
      "finished_at":None,"last_heartbeat_at":None,"attempt":attempt,"bridge_attempt":attempt,"codex_attempt":0,
      "branch":None,"commit":None,"pr_url":None,"pr_number":None,"error":None,"blocked_reason":None,
      "evidence_summary":"","acceptance":{"satisfied":0,"total":0},"test_summary":"No verification evidence","log_path":None,"recent_log_tail":[],
      "execution_complete":False,"review_decision":None,"review_reason":None,"reviewed_at":None}

def transition(record: dict[str, Any], state: str, action: str, **updates: Any) -> dict[str, Any]:
    current=record["state"]
    if state not in STATES or state not in TRANSITIONS[current]: raise ValueError(f"Invalid task transition: {current} -> {state}")
    stamp=now(); record.update(updates); record.update(state=state,current_action=action,updated_at=stamp)
    if state == "running" and not record.get("started_at"): record["started_at"]=stamp
    if state in TERMINAL_STATES: record["finished_at"]=stamp
    return record

def heartbeat(record: dict[str, Any], action: str | None = None, stamp: str | None = None) -> None:
    stamp=stamp or now(); record["last_heartbeat_at"]=stamp; record["updated_at"]=stamp
    if action: record["current_action"]=action

def is_stale(record: dict[str, Any], threshold_seconds: int = 180, reference: datetime | None = None) -> bool:
    if record.get("state") != "running" or not record.get("last_heartbeat_at"): return False
    value=datetime.fromisoformat(record["last_heartbeat_at"].replace("Z", "+00:00"))
    return ((reference or datetime.now(timezone.utc))-value).total_seconds() > threshold_seconds

def write_report(root: Path, task_id: str, report: dict[str, Any]) -> Path:
    report={"schema_version":SCHEMA_VERSION, **report}; path=root/"reports"/f"{task_id}.json"; atomic_json(path, report); return path
