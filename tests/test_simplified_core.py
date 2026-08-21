from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from project_brain_simplified.context import read_project_context
from project_brain_simplified.mcp_server import validate_loopback
from project_brain_simplified.runner import execute_task
from project_brain_simplified.runtime import RuntimePaths
from project_brain_simplified.service import Service
from project_brain_simplified.store import Store


def run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=True)


class SimplifiedCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run("git", "init", "-b", "main", cwd=self.repo)
        run("git", "config", "user.name", "Test", cwd=self.repo)
        run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        (self.repo / ".brain").mkdir()
        (self.repo / ".brain" / "problem.md").write_text("# Problem\nThin bridge\n", encoding="utf-8")
        (self.repo / ".brain" / "current.md").write_text("# Current\nBuild core\n", encoding="utf-8")
        (self.repo / ".brain" / "decisions.md").write_text("# Decisions\nNo auto commit\n", encoding="utf-8")
        run("git", "add", ".", cwd=self.repo)
        run("git", "commit", "-m", "base", cwd=self.repo)
        self.main_sha = run("git", "rev-parse", "main", cwd=self.repo).stdout.strip()
        self.runtime = RuntimePaths.from_value(self.root / "runtime").ensure()
        self.service = Service(self.runtime)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fake_codex(
        self,
        *,
        exit_code: int = 0,
        commit: bool = False,
        counter: Path | None = None,
        large_bytes: int = 0,
        delay: float = 0,
    ) -> Path:
        script = self.root / f"fake_codex_{exit_code}_{int(commit)}_{large_bytes}_{delay}.py"
        counter_code = (
            f"pathlib.Path({str(counter)!r}).open('a', encoding='utf-8').write('run\\n')\n"
            if counter
            else ""
        )
        large_code = (
            f"pathlib.Path('large.txt').write_text('x' * {large_bytes}, encoding='utf-8')\n"
            if large_bytes
            else ""
        )
        script.write_text(
            "import pathlib, subprocess, sys, time\n"
            "prompt=sys.stdin.read()\n"
            + counter_code
            + f"time.sleep({delay})\n"
            + "pathlib.Path('feature.txt').write_text('implemented\\n', encoding='utf-8')\n"
            + large_code
            + (
                "subprocess.run(['git','add','feature.txt'], check=True)\nsubprocess.run(['git','commit','-m','bad commit'], check=True)\n"
                if commit
                else ""
            )
            + f"print('implemented; no publish; prompt_has_policy=', 'Do not commit.' in prompt)\nsys.exit({exit_code})\n",
            encoding="utf-8",
        )
        return script

    def _write_long_lived_codex(self) -> Path:
        script = self.root / "long_lived_codex.py"
        script.write_text(
            "import pathlib, sys, time\n"
            "sys.stdin.read()\n"
            "pathlib.Path('active.txt').write_text('active\\n', encoding='utf-8')\n"
            "counter = 0\n"
            "while True:\n"
            "    pathlib.Path('ticks.txt').write_text(str(counter), encoding='utf-8')\n"
            "    counter += 1\n"
            "    time.sleep(0.02)\n",
            encoding="utf-8",
        )
        return script

    def _write_contract_codex(self, prompt_path: Path, mode_path: Path) -> Path:
        script = self.root / "contract_codex.py"
        script.write_text(
            "import os, pathlib, sys\n"
            f"pathlib.Path({str(prompt_path)!r}).write_text(sys.stdin.read(), encoding='utf-8')\n"
            f"pathlib.Path({str(mode_path)!r}).write_text(os.environ.get('PONYTAIL_DEFAULT_MODE', ''), encoding='utf-8')\n"
            "pathlib.Path('feature.txt').write_text('implemented\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        return script

    def _register(self, codex_script: Path, checks: list[list[str]] | None = None) -> None:
        self.service.register_project(
            project_id="demo",
            name="Demo",
            repo_path=str(self.repo),
            default_branch="main",
            codex_command=[sys.executable, str(codex_script)],
            checks=checks or [],
        )

    def _run_sync(self, goal: str = "Implement feature", ponytail_mode: str | None = None) -> dict:
        task = self.service.store.create_task(
            project_id="demo",
            goal=goal,
            prompt="Create feature.txt",
            ponytail_mode=ponytail_mode,
        )
        self.service.store.claim_task(task["task_id"], pid=os.getpid())
        return execute_task(self.service.store, self.runtime, task["task_id"])

    def _wait_for_terminal(self, task_id: str, timeout: float = 8.0) -> dict:
        deadline = time.monotonic() + timeout
        result = self.service.tasks_get(task_id)
        while result["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.03)
            result = self.service.tasks_get(task_id)
        self.assertIn(result["status"], {"completed", "failed"})
        return result

    def test_project_context_reads_only_three_memory_files(self) -> None:
        value = read_project_context(self.repo)
        self.assertEqual(value["missing"], [])
        self.assertIn("Thin bridge", value["context"]["problem"])
        self.assertIn("Build core", value["context"]["current"])
        self.assertIn("No auto commit", value["context"]["decisions"])

    def test_success_keeps_main_unchanged_and_returns_diff(self) -> None:
        script = self._write_fake_codex()
        self._register(script, checks=[[sys.executable, "-c", "import pathlib; assert pathlib.Path('feature.txt').read_text() == 'implemented\\n'"]])
        result = self._run_sync()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(run("git", "rev-parse", "main", cwd=self.repo).stdout.strip(), self.main_sha)
        self.assertEqual(run("git", "status", "--porcelain", cwd=self.repo).stdout, "")
        self.assertIn("feature.txt", result["changed_files"])
        self.assertIn("+++ b/feature.txt", result["diff_text"])
        self.assertEqual(result["checks"][0]["status"], "passed")
        self.assertEqual(result["base_sha"], self.main_sha)
        self.assertTrue(result["worktree_path"])
        self.assertTrue(Path(result["worktree_path"]).is_dir())
        self.assertIsNone(result["error"])

    def test_failed_check_stops_and_keeps_code_for_review(self) -> None:
        script = self._write_fake_codex()
        self._register(script, checks=[[sys.executable, "-c", "raise SystemExit(3)"]])
        result = self._run_sync()
        self.assertEqual(result["status"], "failed")
        self.assertIn("feature.txt", result["changed_files"])
        self.assertEqual(result["checks"][0]["exit_code"], 3)
        self.assertIn("registered checks failed", result["error"])

    def test_codex_commit_is_policy_failure_and_not_hidden(self) -> None:
        script = self._write_fake_codex(commit=True)
        self._register(script)
        result = self._run_sync()
        self.assertEqual(result["status"], "failed")
        self.assertIn("created a commit", result["error"])
        self.assertIn("feature.txt", result["changed_files"])
        self.assertIn("+++ b/feature.txt", result["diff_text"])
        self.assertEqual(run("git", "rev-parse", "main", cwd=self.repo).stdout.strip(), self.main_sha)

    def test_codex_failure_keeps_partial_changes(self) -> None:
        script = self._write_fake_codex(exit_code=7)
        self._register(script)
        result = self._run_sync()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["codex_exit_code"], 7)
        self.assertIn("feature.txt", result["changed_files"])
        self.assertIn("exited with code 7", result["error"])

    def test_ponytail_default_prefix_and_child_environment(self) -> None:
        prompt_path = self.root / "prompt.txt"
        mode_path = self.root / "mode.txt"
        self._register(self._write_contract_codex(prompt_path, mode_path))
        with patch.dict(os.environ):
            os.environ.pop("PROJECT_BRAIN_PONYTAIL_MODE", None)
            result = self._run_sync()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["ponytail_mode"], None)
        self.assertTrue(
            prompt_path.read_text(encoding="utf-8").startswith("@ponytail lite\n\n")
        )
        self.assertIn("Implementation brief:\nCreate feature.txt\n", prompt_path.read_text(encoding="utf-8"))
        self.assertEqual(mode_path.read_text(encoding="utf-8"), "lite")

    def test_ponytail_host_override_task_override_and_off(self) -> None:
        prompt_path = self.root / "prompt.txt"
        mode_path = self.root / "mode.txt"
        self._register(self._write_contract_codex(prompt_path, mode_path))
        with patch.dict(os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "full"}):
            host_result = self._run_sync()
            self.assertEqual(host_result["status"], "completed")
            self.assertTrue(
                prompt_path.read_text(encoding="utf-8").startswith("@ponytail full\n\n")
            )
            self.assertEqual(mode_path.read_text(encoding="utf-8"), "full")

            result = self._run_sync(ponytail_mode="off")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["ponytail_mode"], "off")
        self.assertTrue(
            prompt_path.read_text(encoding="utf-8").startswith("@ponytail off\n\n")
        )
        self.assertEqual(mode_path.read_text(encoding="utf-8"), "off")

    def test_invalid_ponytail_mode_fails_before_codex(self) -> None:
        marker = self.root / "codex-ran.txt"
        self._register(self._write_fake_codex(counter=marker))
        with patch.dict(os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "invalid"}):
            with self.assertRaisesRegex(ValueError, "ponytail_mode must be one of"):
                self.service.task_run(project_id="demo", goal="Invalid", prompt="Do it")
        self.assertFalse(marker.exists())
        self.assertEqual(self.service.store.list_tasks(), [])

    def test_async_task_run_finishes_without_touching_dirty_main_checkout(self) -> None:
        script = self._write_fake_codex()
        self._register(script)
        run("git", "switch", "-c", "user-work", cwd=self.repo)
        (self.repo / "README.md").write_text("user edit\n", encoding="utf-8")
        (self.repo / "keep.txt").write_text("keep\n", encoding="utf-8")
        before_head = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        before_status = run("git", "status", "--porcelain", cwd=self.repo).stdout

        started = self.service.task_run(project_id="demo", goal="Async", prompt="Create feature.txt")
        self.assertEqual(started["status"], "started")
        task_id = started["task"]["task_id"]
        result = None
        for _ in range(100):
            result = self.service.tasks_get(task_id)
            if result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(run("git", "branch", "--show-current", cwd=self.repo).stdout.strip(), "user-work")
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), before_head)
        self.assertEqual(run("git", "status", "--porcelain", cwd=self.repo).stdout, before_status)

    def test_failed_check_records_start_error_and_does_not_retry(self) -> None:
        script = self._write_fake_codex()
        self._register(script, checks=[["definitely-not-a-real-check"]])
        result = self._run_sync()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"][0]["status"], "failed")
        self.assertEqual(result["checks"][0]["exit_code"], 127)
        self.assertIn("Could not start process", result["checks"][0]["stderr"])

    def test_context_rejects_brain_symlink(self) -> None:
        outside = self.root / "outside.md"
        outside.write_text("secret\n", encoding="utf-8")
        problem = self.repo / ".brain" / "problem.md"
        problem.unlink()
        problem.symlink_to(outside)
        value = read_project_context(self.repo)
        self.assertNotIn("problem", value["context"])
        self.assertIn(".brain/problem.md", value["missing"])

    def test_existing_non_simplified_database_is_not_migrated(self) -> None:
        database = self.root / "old.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE old_tasks(id INTEGER)")
        with self.assertRaisesRegex(RuntimeError, "refusing migration"):
            Store(database).initialize()

    def test_task_run_exact_duplicate_is_idempotent(self) -> None:
        counter = self.root / "counter.log"
        script = self._write_fake_codex(counter=counter, delay=0.25)
        self._register(script)
        first = self.service.task_run(project_id="demo", goal="Same", prompt="Same prompt")
        second = self.service.task_run(project_id="demo", goal="Same", prompt="Same prompt")
        self.assertEqual(first["task"]["task_id"], second["task"]["task_id"])
        self.assertEqual(second["status"], "existing")
        self._wait_for_terminal(first["task"]["task_id"])
        self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])

    def test_task_run_concurrent_duplicate_has_one_worker(self) -> None:
        counter = self.root / "counter.log"
        script = self._write_fake_codex(counter=counter, delay=0.25)
        self._register(script)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self.service.task_run(
                        project_id="demo", goal="Concurrent", prompt="Same concurrent prompt"
                    ),
                    range(2),
                )
            )
        self.assertEqual(results[0]["task"]["task_id"], results[1]["task"]["task_id"])
        self._wait_for_terminal(results[0]["task"]["task_id"])
        self.assertEqual(counter.read_text(encoding="utf-8").splitlines(), ["run"])

    def test_same_request_after_completed_starts_new_task(self) -> None:
        counter = self.root / "counter.log"
        script = self._write_fake_codex(counter=counter)
        self._register(script)
        first = self.service.task_run(project_id="demo", goal="Repeat", prompt="Repeat prompt")
        self._wait_for_terminal(first["task"]["task_id"])
        second = self.service.task_run(project_id="demo", goal="Repeat", prompt="Repeat prompt")
        self.assertNotEqual(first["task"]["task_id"], second["task"]["task_id"])
        self._wait_for_terminal(second["task"]["task_id"])
        self.assertEqual(len(counter.read_text(encoding="utf-8").splitlines()), 2)

    def test_same_request_after_failed_starts_new_task(self) -> None:
        counter = self.root / "counter.log"
        script = self._write_fake_codex(counter=counter, exit_code=9)
        self._register(script)
        first = self.service.task_run(project_id="demo", goal="Fail repeat", prompt="Fail repeat prompt")
        self.assertEqual(self._wait_for_terminal(first["task"]["task_id"])["status"], "failed")
        second = self.service.task_run(project_id="demo", goal="Fail repeat", prompt="Fail repeat prompt")
        self.assertNotEqual(first["task"]["task_id"], second["task"]["task_id"])
        self.assertEqual(self._wait_for_terminal(second["task"]["task_id"])["status"], "failed")
        self.assertEqual(len(counter.read_text(encoding="utf-8").splitlines()), 2)

    def test_task_run_different_request_creates_new_task(self) -> None:
        counter = self.root / "counter.log"
        script = self._write_fake_codex(counter=counter)
        self._register(script)
        first = self.service.task_run(project_id="demo", goal="One", prompt="One prompt")
        second = self.service.task_run(project_id="demo", goal="Two", prompt="Two prompt")
        self.assertNotEqual(first["task"]["task_id"], second["task"]["task_id"])
        self._wait_for_terminal(first["task"]["task_id"])
        self._wait_for_terminal(second["task"]["task_id"])
        self.assertEqual(len(counter.read_text(encoding="utf-8").splitlines()), 2)

    def test_worker_crash_does_not_leave_codex_writing_uncontrolled(self) -> None:
        script = self._write_long_lived_codex()
        self._register(script)
        started = self.service.task_run(project_id="demo", goal="Crash", prompt="Long task")
        task_id = started["task"]["task_id"]
        task = self.service.store.get_task(task_id)
        deadline = time.monotonic() + 5
        while (
            not task.get("worker_pid")
            or not task.get("codex_supervisor_pid")
            or not task.get("worktree_path")
            or not (Path(task["worktree_path"]) / "active.txt").exists()
        ) and time.monotonic() < deadline:
            time.sleep(0.03)
            task = self.service.store.get_task(task_id)
        self.assertTrue(task.get("worker_pid"))
        self.assertTrue(task.get("codex_supervisor_pid"))
        self.assertTrue((Path(task["worktree_path"]) / "active.txt").exists())
        os.kill(task["worker_pid"], signal.SIGKILL)

        observed_running_while_supervisor_alive = False
        deadline = time.monotonic() + 8
        result = self.service.tasks_get(task_id)
        while time.monotonic() < deadline:
            supervisor_state = self.service._process_state(task["codex_supervisor_pid"])
            result = self.service.tasks_get(task_id)
            if supervisor_state == "alive":
                observed_running_while_supervisor_alive = True
                self.assertEqual(result["status"], "running")
            if result["status"] == "failed":
                break
            time.sleep(0.02)
        self.assertTrue(observed_running_while_supervisor_alive)
        self.assertEqual(result["status"], "failed")
        ticks_before = (Path(task["worktree_path"]) / "ticks.txt").read_text(encoding="utf-8")
        time.sleep(0.2)
        ticks_after = (Path(task["worktree_path"]) / "ticks.txt").read_text(encoding="utf-8")
        self.assertEqual(ticks_before, ticks_after)

    def test_large_diff_signals_truncation(self) -> None:
        script = self._write_fake_codex(large_bytes=140000)
        self._register(script)
        result = self._run_sync()
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["diff_size"], 120000)
        self.assertEqual(result["diff_truncated"], 1)
        self.assertEqual(len(result["diff_text"]), 120000)

    def test_checks_fail_fast_after_first_failure(self) -> None:
        script = self._write_fake_codex()
        self._register(
            script,
            checks=[
                [sys.executable, "-c", "raise SystemExit(4)"],
                [
                    sys.executable,
                    "-c",
                    "import pathlib; pathlib.Path('should-not-run.marker').write_text('bad')",
                ],
            ],
        )
        result = self._run_sync()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["status"], "failed")
        self.assertFalse(Path(result["worktree_path"], "should-not-run.marker").exists())

    def test_mcp_bind_allows_only_supported_loopback_hosts(self) -> None:
        validate_loopback("127.0.0.1", 7677)
        validate_loopback("::1", 7677)
        with self.assertRaisesRegex(ValueError, "127.0.0.1 or ::1"):
            validate_loopback("127.0.0.2", 7677)


if __name__ == "__main__":
    unittest.main()
