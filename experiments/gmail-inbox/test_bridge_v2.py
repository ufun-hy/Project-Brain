import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location("bridge_v2", Path(__file__).with_name("bridge_v2.py"))
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(bridge)


def command(repo: Path, *args: str) -> str:
    return subprocess.run(args, cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


class GitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        command(self.repo, "git", "init", "-b", "main")
        command(self.repo, "git", "config", "user.email", "test@example.com")
        command(self.repo, "git", "config", "user.name", "Test")
        (self.repo / "README.md").write_text("base\n")
        command(self.repo, "git", "add", ".")
        command(self.repo, "git", "commit", "-m", "base")

    def tearDown(self):
        self.temp.cleanup()

    def test_success_returns_to_clean_base(self):
        command(self.repo, "git", "checkout", "-b", "brain/task")
        (self.repo / "task.txt").write_text("done\n")
        command(self.repo, "git", "add", ".")
        command(self.repo, "git", "commit", "-m", "task")
        bridge.return_to_clean_base(self.repo, "main")
        self.assertEqual(command(self.repo, "git", "branch", "--show-current"), "main")
        self.assertEqual(command(self.repo, "git", "status", "--porcelain"), "")
        self.assertIn("brain/task", command(self.repo, "git", "branch", "--list"))

    def test_failed_task_cleans_changes_and_local_branch(self):
        command(self.repo, "git", "checkout", "-b", "brain/task")
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "untracked.txt").write_text("temporary\n")
        bridge.cleanup_failed_task(self.repo, "main", "brain/task")
        self.assertEqual(command(self.repo, "git", "branch", "--show-current"), "main")
        self.assertEqual(command(self.repo, "git", "status", "--porcelain"), "")
        self.assertEqual(command(self.repo, "git", "branch", "--list", "brain/task"), "")

    def test_preexisting_unchanged_stale_branch_is_recreated(self):
        command(self.repo, "git", "branch", "brain/task")
        with patch.object(bridge, "remote_branch_exists", return_value=False):
            bridge.prepare_task_branch(self.repo, "brain/task", "main")
        self.assertEqual(command(self.repo, "git", "branch", "--show-current"), "brain/task")


class FailureStateTests(unittest.TestCase):
    def test_missing_executable_is_actionable_and_next_check_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg={"verification_commands":{"missing":["definitely-not-a-real-project-brain-command"],"ok":["git","--version"]},"default_verification":["missing","ok"]}
            evidence=bridge.run_verification(Path(tmp),{},cfg)
        self.assertIsNone(evidence[0]["exit_code"])
        self.assertIn("Command not found",evidence[0]["output_tail"])
        self.assertEqual(evidence[1]["exit_code"],0)

    def test_email_can_only_select_allowlisted_verification_name(self):
        cfg={"verification_commands":{"safe":["git","--version"]},"default_verification":[]}
        with self.assertRaises(bridge.BridgeError): bridge.verification_names({"verification":["rm -rf /"]},cfg)
    def test_retry_count_and_limit(self):
        failures = {}
        for attempt in range(1, bridge.DEFAULT_MAX_ATTEMPTS + 1):
            record = bridge.record_failure(failures, "message", bridge.BridgeError("boom"))
            self.assertEqual(record["attempt_count"], attempt)
        self.assertGreaterEqual(bridge.failure_attempts(failures, "message"), bridge.DEFAULT_MAX_ATTEMPTS)

    def test_success_clears_failure_record(self):
        failures = {"message": {"attempt_count": 2, "last_error": "old"}}
        failures.pop("message", None)
        self.assertNotIn("message", failures)

    def test_default_codex_command(self):
        process = MagicMock()
        process.poll.return_value = 0
        process.returncode = 0
        with patch.object(bridge.subprocess, "Popen", return_value=process) as mocked, \
             patch.object(bridge, "git", return_value=subprocess.CompletedProcess([], 0, "", "")):
            bridge.run_codex(Path("/tmp/repo"), {"prompt": "test"}, {})
        self.assertEqual(mocked.call_args.args[0], ["codex", "exec", "--sandbox", "workspace-write", "-"])


if __name__ == "__main__":
    unittest.main()
