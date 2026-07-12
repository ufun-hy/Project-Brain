import importlib.util, json, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE=Path(__file__).parent
import sys; sys.path.insert(0,str(HERE))
from task_status import StatusStore, heartbeat, is_stale, new_record, transition, write_report
from gmail_callback import FakeCallback
import status_cli
from unittest.mock import patch

class StatusTests(unittest.TestCase):
 def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.store=StatusStore(Path(self.tmp.name))
 def tearDown(self): self.tmp.cleanup()
 def test_transitions_never_auto_accept(self):
  r=new_record("m1","Project-Brain","Demo"); transition(r,"claimed","claimed"); transition(r,"running","active"); transition(r,"awaiting_review","done")
  self.assertEqual(r["state"],"awaiting_review")
  with self.assertRaises(ValueError): transition(r,"running","invalid")
 def test_atomic_persistence_and_recovery(self):
  r=new_record("m1","P","T"); self.store.save(r); self.assertEqual(StatusStore(Path(self.tmp.name)).load("m1"),r)
  self.assertEqual(list((Path(self.tmp.name)/"tasks").glob(".*")),[])
 def test_heartbeat_and_stale(self):
  r=new_record("m","P","T"); transition(r,"claimed","c"); transition(r,"running","r")
  old=(datetime.now(timezone.utc)-timedelta(seconds=181)).isoformat(); heartbeat(r,stamp=old)
  self.assertTrue(is_stale(r,180)); heartbeat(r); self.assertFalse(is_stale(r,180))
 def test_failure_and_blocked(self):
  for state in ("failed","blocked"):
   r=new_record(state,"P","T"); transition(r,state,state,error="boom"); self.assertEqual(r["state"],state)
 def test_structured_report(self):
  p=write_report(Path(self.tmp.name),"m",{"summary":"done","changed_files":["a"],"commands_tests":[{"exit_code":0}],"acceptance_criteria":[{"status":"unknown","evidence":"review"}],"known_gaps":[],"errors":[],"branch":"b","commit":"c","pr_url":"u","started_at":"s","finished_at":"f","bridge_attempt":1,"codex_attempt":1})
  data=json.loads(p.read_text()); self.assertTrue({"changed_files","commands_tests","acceptance_criteria","known_gaps","pr_url"} <= data.keys())
 def test_callback_terminal_selection(self):
  fake=FakeCallback(); original={}
  for state in ("running","awaiting_review","blocked","failed","accepted"):
   fake.send(original,{"state":state})
  self.assertEqual([x[1]["state"] for x in fake.sent],["awaiting_review","blocked","failed"])
 def test_review_cli(self):
  r=new_record("review-me","P","T"); transition(r,"claimed","c"); transition(r,"running","r"); transition(r,"awaiting_review","ready"); self.store.save(r)
  with patch.object(sys,"argv",["status_cli.py","--runtime-dir",self.tmp.name,"review","review-me","accepted","--reason","approved"]): self.assertEqual(status_cli.main(),0)
  self.assertEqual(self.store.load("review-me")["state"],"accepted")

if __name__=="__main__": unittest.main()
