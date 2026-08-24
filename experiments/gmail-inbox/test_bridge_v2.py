import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
        completed = subprocess.CompletedProcess(bridge.DEFAULT_CODEX_COMMAND, 0, "", "")
        with patch.object(bridge.subprocess, "run", return_value=completed) as mocked, \
             patch.object(bridge, "git", return_value=subprocess.CompletedProcess([], 0, "", "")):
            bridge.run_codex(Path("/tmp/repo"), {"prompt": "test"}, {})
        self.assertEqual(mocked.call_args.args[0], ["codex", "exec", "--sandbox", "workspace-write", "-"])


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.repo.mkdir()
        command(self.repo, "git", "init", "-b", "main")
        command(self.repo, "git", "config", "user.email", "test@example.com")
        command(self.repo, "git", "config", "user.name", "Test")
        (self.repo / "README.md").write_text("base\n")
        command(self.repo, "git", "add", ".")
        command(self.repo, "git", "commit", "-m", "base")
        command(self.root, "git", "init", "--bare", str(self.remote))
        command(self.repo, "git", "remote", "add", "origin", str(self.remote))
        command(self.repo, "git", "push", "-u", "origin", "main")
        self.config = {
            "projects": {
                "test": {"path": str(self.repo), "base_branch": "main"}
            },
            "cleanup_local_task_branches": True,
        }
        self.results = self.root / "results"
        self.previous_results_dir = bridge.RESULTS_DIR
        bridge.RESULTS_DIR = self.results

    def tearDown(self):
        bridge.RESULTS_DIR = self.previous_results_dir
        self.temp.cleanup()

    def make_task(self, *, branch="brain/codex-a123", push=True):
        command(self.repo, "git", "checkout", "-b", branch)
        (self.repo / "task.txt").write_text("done\n")
        command(self.repo, "git", "add", ".")
        command(self.repo, "git", "commit", "-m", "task")
        commit = command(self.repo, "git", "rev-parse", "HEAD")
        if push:
            command(self.repo, "git", "push", "-u", "origin", branch)
        command(self.repo, "git", "checkout", "main")
        result = {
            "message_id": "message-a123",
            "task_status": "completed",
            "project": "test",
            "repo": str(self.repo),
            "branch": branch,
            "commit": commit,
            "pushed": True,
        }
        result_path = self.results / "message-a123.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result, result_path, commit

    def test_success_deletes_only_exact_local_branch_and_keeps_remote(self):
        result, result_path, commit = self.make_task()
        cleanup = bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(cleanup["status"], "completed")
        self.assertTrue(cleanup["local_branch_removed"])
        self.assertEqual(command(self.repo, "git", "branch", "--list", result["branch"]), "")
        self.assertEqual(
            command(self.repo, "git", "ls-remote", "--heads", "origin", result["branch"]).split()[0],
            commit,
        )

    def test_missing_local_branch_is_idempotent(self):
        result, result_path, _ = self.make_task()
        command(self.repo, "git", "branch", "-D", "--", result["branch"])
        cleanup = bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(cleanup["status"], "already_absent")
        self.assertTrue(cleanup["local_branch_removed"])

    def test_missing_result_is_retained(self):
        result, _result_path, _ = self.make_task()
        missing = self.results / "missing.json"
        result["message_id"] = "missing"
        self.assertEqual(
            bridge.cleanup_local_branch(result, self.config, missing)["reason"],
            "invalid_result",
        )

    def test_invalid_repo_is_retained(self):
        result, result_path, _ = self.make_task()
        result["repo"] = str(self.root / "other")
        self.assertEqual(
            bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
            "repo_mismatch",
        )

    def test_untrusted_and_protected_branch_names_are_retained(self):
        for branch, reason in (
            ("brain/not_allowed_underscore", "untrusted_branch_name"),
            ("main", "protected_branch"),
            ("restore/gmail", "protected_branch"),
            ("feature/gmail", "protected_branch"),
        ):
            with self.subTest(branch=branch):
                result = {
                    "message_id": "message-a123",
                    "task_status": "completed",
                    "project": "test",
                    "repo": str(self.repo),
                    "branch": branch,
                    "commit": "a" * 40,
                    "pushed": True,
                }
                result_path = self.results / "message-a123.json"
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(result), encoding="utf-8")
                self.assertEqual(
                    bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
                    reason,
                )

    def test_dirty_repository_is_retained(self):
        result, result_path, _ = self.make_task()
        (self.repo / "dirty.txt").write_text("do not remove\n")
        cleanup = bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(cleanup["reason"], "dirty_repository")
        self.assertTrue(bridge.local_branch_exists(self.repo, result["branch"]))

    def test_git_operation_is_retained(self):
        result, result_path, _ = self.make_task()
        lock = bridge._git_path(self.repo, "index.lock")
        lock.touch()
        try:
            self.assertEqual(
                bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
                "git_operation_in_progress",
            )
        finally:
            lock.unlink()

    def test_local_sha_mismatch_is_retained(self):
        result, result_path, _ = self.make_task()
        result["commit"] = command(self.repo, "git", "rev-parse", "main")
        self.assertEqual(
            bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
            "local_sha_mismatch",
        )

    def test_not_pushed_is_retained(self):
        result, result_path, _ = self.make_task()
        result["pushed"] = False
        self.assertEqual(
            bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
            "not_pushed",
        )

    def test_missing_remote_branch_is_retained(self):
        result, result_path, _ = self.make_task(push=False)
        self.assertEqual(
            bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
            "remote_branch_missing",
        )

    def test_remote_sha_mismatch_is_retained(self):
        result, result_path, _ = self.make_task()
        with patch.object(bridge, "_remote_branch_sha", return_value="b" * 40):
            self.assertEqual(
                bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
                "remote_sha_mismatch",
            )

    def test_branch_checked_out_elsewhere_is_retained(self):
        result, result_path, _ = self.make_task()
        other = self.root / "other"
        command(self.repo, "git", "worktree", "add", str(other), result["branch"])
        try:
            self.assertEqual(
                bridge.cleanup_local_branch(result, self.config, result_path)["reason"],
                "branch_checked_out_elsewhere",
            )
        finally:
            command(self.repo, "git", "worktree", "remove", "--force", str(other))

    def test_cleanup_failure_is_pending_and_does_not_touch_failures(self):
        result, result_path, _ = self.make_task()
        failures_path = self.root / "failures.json"
        failures_path.write_text('{"message-a123":{"attempt_count":1}}\n')
        with patch.object(bridge, "_remote_branch_sha", side_effect=bridge.BridgeError("temporary")):
            cleanup = bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(cleanup["status"], "pending")
        self.assertEqual(failures_path.read_text(), '{"message-a123":{"attempt_count":1}}\n')

    def test_pending_cleanup_retry_does_not_call_codex(self):
        result, result_path, _ = self.make_task()
        result["cleanup"] = bridge.initial_cleanup(result)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        with patch.object(bridge, "run_codex", side_effect=AssertionError("Codex must not run")):
            retry = bridge.retry_pending_cleanups(self.config)
        self.assertEqual(retry[0]["cleanup"]["status"], "completed")
        self.assertFalse(bridge.local_branch_exists(self.repo, result["branch"]))

    def test_remote_branch_is_never_deleted(self):
        result, result_path, commit = self.make_task()
        bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(
            command(self.repo, "git", "ls-remote", "--heads", "origin", result["branch"]).split()[0],
            commit,
        )

    def test_cleanup_disabled_retains_branch(self):
        result, result_path, _ = self.make_task()
        config = {**self.config, "cleanup_local_task_branches": False}
        cleanup = bridge.cleanup_local_branch(result, config, result_path)
        self.assertEqual(cleanup["status"], "retained")
        self.assertEqual(cleanup["reason"], "cleanup_disabled")
        self.assertTrue(bridge.local_branch_exists(self.repo, result["branch"]))

    def test_incomplete_task_result_is_retained(self):
        result, result_path, _ = self.make_task()
        result["task_status"] = "failed"
        cleanup = bridge.cleanup_local_branch(result, self.config, result_path)
        self.assertEqual(cleanup["status"], "retained")
        self.assertEqual(cleanup["reason"], "invalid_result")

    def test_recovery_worktree_is_never_a_cleanup_target(self):
        result = {
            "message_id": "message-a123",
            "task_status": "completed",
            "project": "recovery",
            "repo": str(bridge.SCRIPT_DIR.parent.parent),
            "branch": "brain/codex-a123",
            "commit": "a" * 40,
            "pushed": True,
        }
        result_path = self.results / "message-a123.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        config = {"projects": {"recovery": {"path": result["repo"], "base_branch": "main"}}}
        cleanup = bridge.cleanup_local_branch(result, config, result_path)
        self.assertEqual(cleanup["status"], "retained")
        self.assertEqual(cleanup["reason"], "recovery_worktree")

    def test_completed_result_reconciles_processed_identity(self):
        result, result_path, _ = self.make_task()
        state_path = self.root / "processed.json"
        previous_state_path = bridge.STATE_PATH
        bridge.STATE_PATH = state_path
        try:
            state = {"processed_message_ids": []}
            processed = bridge.reconcile_completed_results(state, set())
            self.assertIn(result["message_id"], processed)
            self.assertIn(result["message_id"], json.loads(state_path.read_text())["processed_message_ids"])
        finally:
            bridge.STATE_PATH = previous_state_path


if __name__ == "__main__":
    unittest.main()
