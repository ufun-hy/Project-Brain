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
    def save(self, record: dict[str, Any]) -> None: atomic_json(self.path(record["task_id"]), record)
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
      "evidence_summary":"","acceptance":{"satisfied":0,"total":None},"test_summary":"Not run","log_path":None,"recent_log_tail":[]}

def transition(record: dict[str, Any], state: str, action: str, **updates: Any) -> dict[str, Any]:
    current=record["state"]
    if state not in STATES or state not in TRANSITIONS[current]: raise ValueError(f"Invalid task transition: {current} -> {state}")
    stamp=now(); record.update(updates); record.update(state=state,current_action=action,updated_at=stamp)
    if state == "running" and not record.get("started_at"): record["started_at"]=stamp
    if state in {"accepted","needs_changes","blocked","failed","cancelled"}: record["finished_at"]=stamp
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
