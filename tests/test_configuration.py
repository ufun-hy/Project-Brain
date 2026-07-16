from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from project_brain.cli import main
from project_brain.configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationManager,
    project_checks,
)
from project_brain.errors import ConfigurationError, InvalidTaskError
from project_brain.project_config import canonical_profile_json, config_sha256
from project_brain.store import TaskStore

from tests.helpers import CoreFixture, create_remote_clone, executable_script


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "configured")
        self.manager = ConfigurationManager(self.fixture.store, self.fixture.runtime)

    def tearDown(self) -> None:
        self.fixture.close()

    def project_value(self, project_id: str = "configured", **overrides):
        value = {
            "project_id": project_id,
            "name": project_id,
            "repo_path": str(self.repo),
            "remote_url": str(self.remote),
            "default_branch": "main",
            "codex_command": [sys.executable, "-c", "print('codex')"],
            "verification_commands": [
                {"id": "unit", "text": "Unit", "command": [sys.executable, "-V"]}
            ],
            "allowed_commands": {"format": [sys.executable, "-V"]},
            "auto_push": False,
            "auto_pr": False,
        }
        value.update(overrides)
        return value

    def write_config(self, projects, *, schema=True, extra=None) -> Path:
        value = {"projects": projects}
        if schema:
            value["schema_version"] = CONFIG_SCHEMA_VERSION
        if extra:
            value.update(extra)
        path = self.fixture.root / "projects.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_hash_is_canonical_and_exactly_matches_snapshot_json(self) -> None:
        path = self.write_config([self.project_value()])
        prepared, _, _ = self.manager.prepare(path)
        profile = prepared[0]
        rendered = canonical_profile_json(profile)
        self.assertEqual(config_sha256(profile), hashlib.sha256(rendered.encode()).hexdigest())
        reordered = dict(reversed(list(profile.items())))
        self.assertEqual(config_sha256(reordered), config_sha256(profile))

    def test_schema_v1_relative_codex_is_persisted_and_snapshotted_as_absolute(self) -> None:
        codex = executable_script(self.fixture.root / "fixture-codex", "raise SystemExit(0)\n")
        path = self.write_config(
            [self.project_value(codex_command=[codex.name, "exec", "-"])]
        )
        lookup_path = str(codex.parent) + os.pathsep + os.environ.get("PATH", "")
        with patch.dict(os.environ, {"PATH": lookup_path}):
            self.assertEqual(self.manager.validate(path)["status"], "valid")
            applied = self.manager.apply(path, execute=True)
        stored = self.fixture.store.get_project("configured")
        task = self.fixture.add_task("absolute-snapshot", project_id="configured")
        snapshot = self.fixture.store.task_execution_profile(task)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(stored["codex_command"][0], str(codex.resolve()))
        self.assertEqual(snapshot["codex_command"][0], str(codex.resolve()))
        self.assertTrue(Path(snapshot["codex_command"][0]).is_absolute())
        export = self.fixture.root / "absolute-export.json"
        self.manager.export(export, force=False)
        exported = json.loads(export.read_text(encoding="utf-8"))
        self.assertEqual(exported["projects"][0]["codex_command"][0], str(codex.resolve()))

    def test_example_config_delegates_codex_resolution_to_onboarding(self) -> None:
        example_path = Path(__file__).parents[1] / "config" / "project-brain.example.json"
        example = json.loads(example_path.read_text(encoding="utf-8"))
        self.assertNotIn("codex_command", example["projects"][0])

    def test_absolute_snapshot_launches_with_empty_path(self) -> None:
        path = self.write_config([self.project_value()])
        self.manager.apply(path, execute=True)
        task = self.fixture.add_task("minimal-path", project_id="configured")
        snapshot = self.fixture.store.task_execution_profile(task)
        completed = subprocess.run(
            snapshot["codex_command"],
            input="",
            text=True,
            capture_output=True,
            env={"PATH": ""},
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("codex", completed.stdout)

    def test_config_operations_reject_unavailable_codex_before_write(self) -> None:
        missing = self.fixture.root / "missing-codex"
        path = self.write_config(
            [self.project_value(codex_command=[str(missing), "exec", "-"])]
        )
        operations = (
            lambda: self.manager.validate(path),
            lambda: self.manager.plan(path),
            lambda: self.manager.apply(path, execute=False),
            lambda: self.manager.apply(path, execute=True),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ConfigurationError):
                operation()
        self.assertEqual(self.fixture.store.list_projects(), [])

    def test_projects_add_and_update_reject_unavailable_codex_before_write(self) -> None:
        missing = self.fixture.root / "missing-cli-codex"
        add_runtime = self.fixture.root / "missing-add-runtime"
        add_stdout = io.StringIO()
        add_stderr = io.StringIO()
        with redirect_stdout(add_stdout), redirect_stderr(add_stderr):
            add_code = main(
                [
                    "--runtime-root",
                    str(add_runtime),
                    "projects",
                    "add",
                    str(self.repo),
                    "--project-id",
                    "missing-add",
                    "--codex-path",
                    str(missing),
                    "--non-interactive",
                    "--json",
                ]
            )
        self.assertEqual(add_code, 2)
        self.assertEqual(add_stdout.getvalue(), "")
        self.assertEqual(TaskStore(add_runtime / "project-brain.db").list_projects(), [])

        self.manager.apply(self.write_config([self.project_value()]), execute=True)
        before = self.fixture.store.get_project("configured")
        update_stdout = io.StringIO()
        update_stderr = io.StringIO()
        with redirect_stdout(update_stdout), redirect_stderr(update_stderr):
            update_code = main(
                [
                    "--runtime-root",
                    str(self.fixture.runtime.root),
                    "projects",
                    "update",
                    "configured",
                    "--codex-path",
                    str(missing),
                    "--non-interactive",
                    "--json",
                ]
            )
        self.assertEqual(update_code, 2)
        self.assertEqual(update_stdout.getvalue(), "")
        self.assertEqual(self.fixture.store.get_project("configured"), before)

    def test_revision_changes_only_for_execution_configuration(self) -> None:
        path = self.write_config([self.project_value()])
        first = self.manager.apply(path, execute=True)["results"][0]["project"]
        self.assertEqual(first["config_revision"], 1)
        before = self.fixture.store.get_project("configured")
        noop = self.manager.apply(path, execute=True)["results"][0]
        after = self.fixture.store.get_project("configured")
        self.assertEqual(noop["action"], "noop")
        self.assertEqual(after["updated_at"], before["updated_at"])
        renamed = self.write_config([self.project_value(name="Display only")])
        value = self.manager.apply(renamed, execute=True)["results"][0]["project"]
        self.assertEqual(value["config_revision"], 1)
        changed = self.write_config([self.project_value(name="Display only", auto_push=True)])
        value = self.manager.apply(changed, execute=True)["results"][0]["project"]
        self.assertEqual(value["config_revision"], 2)

    def test_task_atomically_binds_full_profile_and_ignores_later_update(self) -> None:
        old_codex = executable_script(self.fixture.root / "old-codex", "raise SystemExit(0)\n")
        new_codex = executable_script(self.fixture.root / "new-codex", "raise SystemExit(0)\n")
        self.manager.apply(
            self.write_config([self.project_value(codex_command=[str(old_codex), "exec", "-"])]),
            execute=True,
        )
        task = self.fixture.add_task("snapshot", project_id="configured")
        old_profile = self.fixture.store.task_execution_profile(task)
        self.manager.apply(
            self.write_config(
                [
                    self.project_value(
                        default_branch="release",
                        codex_command=[str(new_codex), "exec", "-"],
                        verification_commands=[{"id": "new", "command": [sys.executable, "-V"]}],
                        allowed_commands={"new": [sys.executable, "-V"]},
                        auto_push=True,
                        auto_pr=True,
                    )
                ]
            ),
            execute=True,
        )
        stored = self.fixture.store.get_task("snapshot")
        self.assertEqual(stored["project_config_revision"], 1)
        self.assertEqual(self.fixture.store.task_execution_profile(stored), old_profile)
        self.assertEqual(old_profile["default_branch"], "main")
        self.assertFalse(old_profile["auto_push"])
        self.assertFalse(old_profile["auto_pr"])
        self.assertEqual(old_profile["verification_commands"][0]["id"], "unit")
        self.assertIn("format", old_profile["allowed_commands"])
        self.assertEqual(old_profile["codex_command"][0], str(old_codex.resolve()))
        new_task = self.fixture.add_task("new-snapshot", project_id="configured")
        new_profile = self.fixture.store.task_execution_profile(new_task)
        self.assertEqual(new_profile["codex_command"][0], str(new_codex.resolve()))

    def test_missing_or_tampered_snapshot_never_falls_back_to_active_project(self) -> None:
        self.manager.apply(self.write_config([self.project_value()]), execute=True)
        self.fixture.add_task("tampered", project_id="configured")
        with self.fixture.store.connect() as connection:
            connection.execute(
                "UPDATE tasks SET execution_profile_json = ? WHERE task_id = 'tampered'",
                (json.dumps({"project_id": "configured"}),),
            )
            connection.commit()
        with self.assertRaises(InvalidTaskError):
            self.fixture.store.task_execution_profile("tampered")

    def test_plan_validate_are_read_only_and_omissions_are_registered_only(self) -> None:
        self.manager.apply(self.write_config([self.project_value()]), execute=True)
        empty = self.write_config([])
        before = self.fixture.store.get_project("configured")
        self.assertEqual(self.manager.validate(empty)["status"], "valid")
        plan = self.manager.plan(empty)
        self.assertEqual(plan["registered_only"], ["configured"])
        self.assertEqual(self.fixture.store.get_project("configured"), before)

    def test_multi_project_apply_rolls_back_on_database_constraint(self) -> None:
        repo_two, remote_two = create_remote_clone(self.fixture.root, "configured-two")
        first = self.project_value("one", name="duplicate")
        second = self.project_value(
            "two", name="duplicate", repo_path=str(repo_two), remote_url=str(remote_two)
        )
        path = self.write_config([first, second])
        with self.assertRaises(Exception):
            self.manager.apply(path, execute=True)
        self.assertEqual(self.fixture.store.list_projects(), [])

    def test_legacy_plan_and_one_time_explicit_bootstrap(self) -> None:
        path = self.write_config([self.project_value()], schema=False, extra={"mcp_server": {}})
        self.assertEqual(self.manager.plan(path)["status"], "legacy_schema")
        result = self.manager.apply(path, execute=True)
        self.assertEqual(result["status"], "applied")
        with self.assertRaises(ConfigurationError):
            self.manager.apply(path, execute=True)

    def test_unknown_top_level_and_secret_are_rejected_before_write(self) -> None:
        unknown = self.write_config([self.project_value()], extra={"surprise": True})
        with self.assertRaises(ConfigurationError):
            self.manager.plan(unknown)
        unknown_project = self.write_config([self.project_value(surprise=True)])
        with self.assertRaises(ConfigurationError):
            self.manager.plan(unknown_project)
        invalid_boolean = self.write_config([self.project_value(auto_push="false")])
        with self.assertRaises(ConfigurationError):
            self.manager.plan(invalid_boolean)
        secret = self.write_config(
            [self.project_value(codex_command=[sys.executable, "--token=ghp_abcdefghijklmnopqrstuvwxyz123456"])]
        )
        with self.assertRaises(ConfigurationError):
            self.manager.plan(secret)
        self.assertEqual(self.fixture.store.list_projects(), [])

    def test_export_is_private_atomic_and_requires_force(self) -> None:
        self.manager.apply(self.write_config([self.project_value()]), execute=True)
        target = self.fixture.root / "export.json"
        result = self.manager.export(target, force=False)
        self.assertEqual(result["status"], "exported")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(target.read_text())["schema_version"], CONFIG_SCHEMA_VERSION)
        with self.assertRaises(ConfigurationError):
            self.manager.export(target, force=False)
        self.manager.export(target, force=True)

    def test_export_no_replace_rejects_target_created_at_commit_time(self) -> None:
        self.manager.apply(self.write_config([self.project_value()]), execute=True)
        target = self.fixture.root / "raced-export.json"
        real_link = os.link

        def create_competing_target(source, destination):
            Path(destination).write_text("competitor\n", encoding="utf-8")
            return real_link(source, destination)

        with patch("project_brain.configuration.os.link", side_effect=create_competing_target):
            with self.assertRaises(ConfigurationError):
                self.manager.export(target, force=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "competitor\n")

    def test_project_checks_require_executable_bits_for_codex_and_verification(self) -> None:
        codex = executable_script(self.fixture.root / "checked-codex", "raise SystemExit(0)\n")
        verification = executable_script(
            self.fixture.root / "checked-verification", "raise SystemExit(0)\n"
        )
        path = self.write_config(
            [
                self.project_value(
                    codex_command=[str(codex), "exec", "-"],
                    verification_commands=[
                        {"id": "exec-bit", "command": [str(verification)]}
                    ],
                )
            ]
        )
        self.manager.apply(path, execute=True)
        project = self.fixture.store.get_project("configured")
        passed = project_checks(project, self.fixture.runtime)
        self.assertEqual(passed["status"], "healthy")

        codex.chmod(0o644)
        codex_failed = project_checks(project, self.fixture.runtime)
        self.assertFalse(next(item for item in codex_failed["checks"] if item["name"] == "codex")["passed"])
        self.assertEqual(codex_failed["status"], "unhealthy")

        codex.chmod(0o755)
        verification.chmod(0o644)
        verification_failed = project_checks(project, self.fixture.runtime)
        self.assertFalse(
            next(
                item
                for item in verification_failed["checks"]
                if item["name"] == "verification:exec-bit"
            )["passed"]
        )
        verification.chmod(0o755)
        self.assertEqual(project_checks(project, self.fixture.runtime)["status"], "healthy")

    def test_interactive_json_projects_add_emits_one_stdout_document(self) -> None:
        runtime = self.fixture.root / "interactive-json-runtime"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("builtins.input", return_value="yes"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(
                [
                    "--runtime-root",
                    str(runtime),
                    "projects",
                    "add",
                    str(self.repo),
                    "--project-id",
                    "interactive-json",
                    "--codex-path",
                    sys.executable,
                    "--no-auto-push",
                    "--no-auto-pr",
                    "--json",
                ]
            )
        value = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "applied")
        self.assertIn("Apply this project configuration?", stderr.getvalue())

    def test_cli_init_is_idempotent_and_apply_never_silently_imports(self) -> None:
        runtime = self.fixture.root / "fresh-runtime"
        config = runtime / "config" / "project-brain.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"projects": [self.project_value()]}), encoding="utf-8")
        outputs = []
        rendered = []
        for _ in range(2):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(["--runtime-root", str(runtime), "init", "--json"])
            self.assertEqual(code, 0)
            rendered.append(stream.getvalue())
            outputs.append(json.loads(stream.getvalue())["status"])
        self.assertEqual(outputs, ["initialized", "already_initialized"])
        self.assertNotIn(str(runtime), "".join(rendered))
        stream = io.StringIO()
        with redirect_stdout(stream):
            main(["--runtime-root", str(runtime), "apply", "--json"])
        self.assertEqual(json.loads(stream.getvalue())["status"], "idle")
        self.assertEqual(TaskStore(runtime / "project-brain.db").list_projects(), [])

    def test_projects_cli_add_show_check_and_name_only_update(self) -> None:
        runtime = self.fixture.root / "cli-runtime"

        def invoke(*arguments):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(["--runtime-root", str(runtime), *arguments])
            return code, json.loads(stream.getvalue())

        code, added = invoke(
            "projects", "add", str(self.repo), "--project-id", "cli-project",
            "--codex-path", sys.executable, "--no-auto-push", "--no-auto-pr",
            "--non-interactive", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(added["project"]["config_revision"], 1)
        self.assertEqual(added["plan"]["action"], "add")
        duplicate_stream = io.StringIO()
        with redirect_stdout(duplicate_stream), redirect_stderr(duplicate_stream):
            duplicate_code = main(
                [
                    "--runtime-root", str(runtime), "projects", "add", str(self.repo),
                    "--project-id", "cli-project", "--codex-path", sys.executable,
                    "--non-interactive", "--json",
                ]
            )
        self.assertEqual(duplicate_code, 2)
        code, shown = invoke("projects", "show", "cli-project", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn("repo_path", shown)
        self.assertNotIn("codex_command", shown)
        code, checked = invoke("projects", "check", "cli-project", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(checked["verification_executed"])
        code, updated = invoke(
            "projects", "update", "cli-project", "--name", "Display Name",
            "--non-interactive", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(updated["plan"]["action"], "rename")
        self.assertEqual(updated["project"]["config_revision"], 1)

    def test_config_cli_requires_execute_and_exports_schema(self) -> None:
        path = self.write_config([self.project_value()])
        runtime = self.fixture.root / "config-cli-runtime"

        def invoke(*arguments):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(["--runtime-root", str(runtime), *arguments])
            return code, json.loads(stream.getvalue())

        _, preview = invoke("config", "apply", "--file", str(path), "--json")
        self.assertEqual(preview["status"], "planned")
        self.assertNotIn("source", preview)
        self.assertEqual(TaskStore(runtime / "project-brain.db").list_projects(), [])
        _, applied = invoke("config", "apply", "--file", str(path), "--execute", "--json")
        self.assertEqual(applied["status"], "applied")
        target = self.fixture.root / "cli-export.json"
        _, exported = invoke("config", "export", "--file", str(target), "--json")
        self.assertEqual(exported["status"], "exported")
        self.assertNotIn("path", exported)
        self.assertEqual(json.loads(target.read_text())["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
