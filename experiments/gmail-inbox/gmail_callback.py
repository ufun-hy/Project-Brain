"""Gmail terminal handoff interface; tests use FakeCallback and never send mail."""
from __future__ import annotations
import base64
from email.message import EmailMessage
from typing import Any, Protocol

CALLBACK_STATES={"awaiting_review","blocked","failed"}
class Callback(Protocol):
    def send(self, original: dict[str,str], record: dict[str,Any]) -> None: ...
class FakeCallback:
    def __init__(self): self.sent=[]
    def send(self, original, record):
        if record["state"] in CALLBACK_STATES: self.sent.append((original,record.copy()))
class GmailCallback:
    def __init__(self, service): self.service=service
    def send(self, original, record):
        if record["state"] not in CALLBACK_STATES: return
        msg=EmailMessage(); msg["To"]=original["sender"]; msg["Subject"]="Re: "+original["subject"]
        if original.get("message_id_header"): msg["In-Reply-To"]=msg["References"]=original["message_id_header"]
        msg.set_content(f"Task: {record['task_id']}\nProject: {record['project']}\nStatus: {record['state']}\nResult: {record.get('evidence_summary','')}\nTests: {record.get('test_summary','')}\nDraft PR: {record.get('pr_url') or 'not available'}\n")
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode(); self.service.users().messages().send(userId="me",body={"raw":raw,"threadId":original.get("thread_id")}).execute()
