"""Durable Gmail terminal handoff outbox; heartbeat mail is intentionally unsupported."""
from __future__ import annotations
import base64, hashlib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Protocol
from task_status import atomic_json, bounded, now

CALLBACK_STATES={"awaiting_review","blocked","failed"}
MAX_ATTEMPTS=5

class Callback(Protocol):
    def send(self, original: dict[str,str], record: dict[str,Any]) -> None: ...

class FakeCallback:
    def __init__(self, fail: Exception | None=None): self.sent=[]; self.fail=fail
    def send(self, original, record):
        if record["state"] not in CALLBACK_STATES: return
        if self.fail: raise self.fail
        self.sent.append((original,record.copy()))

class GmailCallback:
    def __init__(self, service): self.service=service
    def send(self, original, record):
        if record["state"] not in CALLBACK_STATES: return
        msg=EmailMessage(); msg["To"]=original["sender"]; msg["Subject"]="Re: "+original["subject"]
        if original.get("message_id_header"): msg["In-Reply-To"]=msg["References"]=original["message_id_header"]
        acceptance=record.get("acceptance",{})
        msg.set_content(f"Task: {record['task_id']}\nProject: {record['project']}\nStatus: {record['state']}\nResult: {record.get('evidence_summary','')}\nAcceptance: {acceptance.get('satisfied',0)}/{acceptance.get('total',0)}\nTests: {record.get('test_summary','')}\nDraft PR: {record.get('pr_url') or 'not available'}\n")
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode(); self.service.users().messages().send(userId="me",body={"raw":raw,"threadId":original.get("thread_id")}).execute()

def outbox_key(task_id: str, state: str) -> str:
    return hashlib.sha256(f"{task_id}:{state}".encode()).hexdigest()[:24]

class CallbackOutbox:
    def __init__(self, root: Path): self.path=root/"callback-outbox.json"
    def load(self) -> dict[str,Any]:
        if not self.path.exists(): return {"schema_version":1,"items":{}}
        import json
        return json.loads(self.path.read_text(encoding="utf-8"))
    def enqueue(self, original: dict[str,str], record: dict[str,Any]) -> str | None:
        if record["state"] not in CALLBACK_STATES: return None
        data=self.load(); key=outbox_key(record["task_id"],record["state"])
        if key not in data["items"]:
            data["items"][key]={"key":key,"task_id":record["task_id"],"state":record["state"],"original":original,
              "record":record,"attempts":0,"created_at":now(),"next_attempt_at":now(),"delivered_at":None,"last_error":None,"reauthorization_required":False}
            atomic_json(self.path,data)
        return key
    def deliver_pending(self, sender: Callback, reference: datetime | None=None) -> list[dict[str,Any]]:
        data=self.load(); reference=reference or datetime.now(timezone.utc); changed=False
        for item in data["items"].values():
            if item["delivered_at"] or item["attempts"]>=MAX_ATTEMPTS: continue
            if datetime.fromisoformat(item["next_attempt_at"].replace("Z","+00:00"))>reference: continue
            try:
                sender.send(item["original"],item["record"]); item["delivered_at"]=now(); item["last_error"]=None
            except Exception as exc:
                item["attempts"]+=1; item["last_error"]=bounded(exc)
                scope="scope" in str(exc).lower() or "insufficient" in str(exc).lower()
                item["reauthorization_required"]=scope
                delay=min(3600,30*(2**(item["attempts"]-1))); item["next_attempt_at"]=(reference+timedelta(seconds=delay)).isoformat()
            changed=True
        if changed: atomic_json(self.path,data)
        return list(data["items"].values())
