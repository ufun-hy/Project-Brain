from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
import unittest

from project_brain.errors import InvalidTaskError
from project_brain.locking import RuntimeLock
from project_brain.application import worker_result_view
from project_brain.mcp.dispatch import OneShotDispatcher

from tests.helpers import CoreFixture, executable_script


class FakeProcess:
    def __init__(self, pid: int = 4321, poll_result: int | None = None) -> None:
        self.pid = pid
        self.returncode = poll_result
        self._finished = threading.Event()
        if poll_result is not None:
            self._finished.set()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        self._finished.wait()
        assert self.returncode is not None
        return self.returncode

    def finish(self, exit_code: int = 0) -> None:
        self.returncode = exit_code
        self._finished.set()


class CapturingPopen:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        process = FakeProcess(pid=4321 + len(self.processes))
        self.processes.append(process)
        return process

    def finish_all(self) -> None:
        for process in self.processes:
            process.finish()


class MCPDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.fixture.add_project()
        self.captures: list[CapturingPopen] = []

    def tearDown(self) -> None:
        for capture in self.captures:
            capture.finish_all()
        expected_exits = sum(len(capture.processes) for capture in self.captures)
        if expected_exits:
            self._wait_for(
                lambda: len(
                    [
                        event
                        for event in self.fixture.store.list_events()
                        if event["event_type"] == "mcp_dispatch_worker_exited"
                    ]
                )
                >= expected_exits
            )
        self.fixture.close()

    @staticmethod
    def _wait_for(condition, *, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("timed out waiting for asynchronous worker reaper")

    def _dispatcher(self, capture: CapturingPopen) -> OneShotDispatcher:
        self.captures.append(capture)
        return OneShotDispatcher(
            self.fixture.store,
            self.fixture.runtime,
            python_executable=sys.executable,
            popen_factory=capture,
            environment={"PATH": os.environ.get("PATH", ""), "EVIL_REQUEST_VALUE": "nope"},
        )

    def test_dispatch_starts_only_fixed_worker_and_returns_immediately(self) -> None:
        self.fixture.add_task("dispatch-me")
        capture = CapturingPopen()
        dispatcher = self._dispatcher(capture)
        result = dispatcher.dispatch(reason="MCP operator requested queue progress")
        self.assertEqual(result["dispatch_status"], "started")
        self.assertEqual(result["worker_pid"], 4321)
        self.assertEqual(len(capture.calls), 1)
        argv, kwargs = capture.calls[0]
        self.assertEqual(argv, dispatcher.worker_argv)
        self.assertEqual(
            argv[1:],
            [
                "-m",
                "project_brain",
                "--runtime-root",
                str(self.fixture.runtime.root),
                "apply",
                "--json",
            ],
        )
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("EVIL_REQUEST_VALUE", kwargs["env"])
        self.assertEqual(kwargs["env"]["PROJECT_BRAIN_WORKER_OUTPUT"], "1")
        self.assertNotIn("MCP operator", json.dumps({"argv": argv, "env": kwargs["env"], "cwd": kwargs["cwd"]}))
        self.assertTrue(kwargs["stdout"].closed)
        log = self.fixture.runtime.logs_dir / "mcp-dispatch" / result["log_id"]
        self.assertEqual(stat.S_IMODE(log.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        header = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(header["event"], "dispatch_requested")
        self.assertEqual(
            self.fixture.store.list_events()[-1]["payload"]["dispatch_status"],
            "launch_requested",
        )

    def test_one_dispatch_starts_at_most_one_active_process(self) -> None:
        self.fixture.add_task("dispatch-once")
        capture = CapturingPopen()
        dispatcher = self._dispatcher(capture)
        first = dispatcher.dispatch()
        second = dispatcher.dispatch()
        self.assertEqual(first["dispatch_status"], "started")
        self.assertEqual(second["dispatch_status"], "already_running")
        self.assertEqual(len(capture.calls), 1)

    def test_runtime_lock_prevents_worker_launch(self) -> None:
        self.fixture.add_task("locked-dispatch")
        capture = CapturingPopen()
        dispatcher = self._dispatcher(capture)
        with RuntimeLock(self.fixture.runtime.lock_file):
            result = dispatcher.dispatch()
        self.assertEqual(result["dispatch_status"], "already_running")
        self.assertEqual(capture.calls, [])

    def test_claim_blocker_prevents_worker_launch(self) -> None:
        self.fixture.add_task("blocked-dispatch")
        self.fixture.store.claim_next()
        self.fixture.store.record_agent_session(
            session_id="session-blocked-dispatch",
            task_id="blocked-dispatch",
            adapter="codex",
            command=["codex", "exec"],
        )
        capture = CapturingPopen()
        result = self._dispatcher(capture).dispatch()
        self.assertEqual(result["dispatch_status"], "blocked")
        self.assertFalse(result["claim_safety"]["claim_safe"])
        self.assertEqual(result["claim_safety"]["blockers"][0]["task_id"], "blocked-dispatch")
        self.assertEqual(capture.calls, [])

    def test_idle_queue_does_not_launch_worker(self) -> None:
        capture = CapturingPopen()
        result = self._dispatcher(capture).dispatch()
        self.assertEqual(result["dispatch_status"], "idle")
        self.assertEqual(capture.calls, [])
        self.assertEqual(
            self.fixture.store.list_events()[-1]["payload"]["dispatch_status"],
            "idle",
        )

    def test_secret_reason_is_rejected_before_log_or_process(self) -> None:
        self.fixture.add_task("secret-reason")
        capture = CapturingPopen()
        with self.assertRaises(InvalidTaskError):
            self._dispatcher(capture).dispatch(
                reason="token sk-abcdefghijklmnopqrstuvwxyz123456 must not persist"
            )
        self.assertEqual(capture.calls, [])
        self.assertFalse((self.fixture.runtime.logs_dir / "mcp-dispatch").exists())

    def test_actual_safe_recovery_worker_writes_private_json_lines(self) -> None:
        self.fixture.add_task("recover-with-worker")
        self.fixture.store.claim_next()
        dispatcher = OneShotDispatcher(
            self.fixture.store,
            self.fixture.runtime,
            python_executable=sys.executable,
        )
        result = dispatcher.dispatch(reason="Recover interrupted state")
        self.assertEqual(result["dispatch_status"], "started")
        self._wait_for(
            lambda: dispatcher._active_process is None
            and any(
                event["event_type"] == "mcp_dispatch_worker_exited"
                for event in self.fixture.store.list_events()
            )
        )
        log = self.fixture.runtime.logs_dir / "mcp-dispatch" / result["log_id"]
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 2)
        values = [json.loads(line) for line in lines]
        self.assertEqual(values[0]["event"], "dispatch_requested")
        self.assertNotIn("payload", json.dumps(values[1]))
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)

    def test_daemon_reaper_audits_exit_and_allows_next_dispatch(self) -> None:
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        worker = executable_script(
            self.fixture.root / "short-worker",
            "import sys\nsys.exit(7)\n",
        )
        self.fixture.add_task("reaper-task")
        dispatcher = OneShotDispatcher(
            self.fixture.store,
            self.fixture.runtime,
            python_executable=str(worker),
            environment={
                "PATH": os.environ.get("PATH", ""),
                "OPENAI_API_KEY": secret,
            },
        )

        first = dispatcher.dispatch(reason="exercise active reaping")
        self.assertEqual(first["dispatch_status"], "started")
        self._wait_for(
            lambda: dispatcher._active_process is None
            and len(
                [
                    event
                    for event in self.fixture.store.list_events()
                    if event["event_type"] == "mcp_dispatch_worker_exited"
                ]
            )
            == 1
        )
        exited = [
            event
            for event in self.fixture.store.list_events()
            if event["event_type"] == "mcp_dispatch_worker_exited"
        ][0]
        self.assertEqual(
            set(exited["payload"]),
            {"dispatch_status", "worker_pid", "exit_code", "log_id"},
        )
        self.assertEqual(exited["payload"]["dispatch_status"], "worker_exited")
        self.assertEqual(exited["payload"]["exit_code"], 7)
        self.assertEqual(exited["payload"]["log_id"], first["log_id"])
        rendered = json.dumps(exited)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(self.fixture.runtime.root), rendered)
        self.assertNotIn("argv", exited["payload"])
        self.assertNotIn("environment", exited["payload"])
        self.assertNotIn("task", exited["payload"])

        second = dispatcher.dispatch(reason="confirm dispatch after reap")
        self.assertEqual(second["dispatch_status"], "started")
        self.assertNotEqual(second["log_id"], first["log_id"])
        self._wait_for(
            lambda: dispatcher._active_process is None
            and len(
                [
                    event
                    for event in self.fixture.store.list_events()
                    if event["event_type"] == "mcp_dispatch_worker_exited"
                ]
            )
            == 2
        )

    def test_worker_result_omits_payload_and_redacts_errors(self) -> None:
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        value = worker_result_view(
            {
                "status": "failed",
                "task": {
                    "task_id": "safe-log",
                    "project_id": "project-one",
                    "status": "failed",
                    "attempt_phase": "implementation",
                    "attempt_count": 1,
                    "payload": {"prompt": f"never log {secret}"},
                    "last_error": f"worker leaked {secret}",
                },
            }
        )
        rendered = json.dumps(value)
        self.assertNotIn("payload", rendered)
        self.assertNotIn(secret, rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
