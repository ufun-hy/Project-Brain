from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from project_brain.cli import _error_payload, build_parser, main
from project_brain.cli_contract import cli_contract_sha256, load_cli_contract
from project_brain.errors import InvalidTaskError


class CLIContractTests(unittest.TestCase):
    def test_contract_command_is_runtime_free_and_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime-must-not-exist"
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    ["--runtime-root", str(runtime), "cli-contract", "--json"]
                )
            rendered = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(runtime.exists())
            self.assertEqual(rendered["status"], "ok")
            self.assertEqual(rendered["contract"], load_cli_contract())
            self.assertEqual(rendered["document_sha256"], cli_contract_sha256())
            self.assertRegex(cli_contract_sha256(), r"^[0-9a-f]{64}$")

    def test_python_parser_accepts_the_shared_native_onboarding_contract(self) -> None:
        contract = load_cli_contract()["operations"]["native_onboarding"]
        options = contract["options"]
        parsed = build_parser().parse_args(
            [
                *contract["command_path"],
                "/tmp/repository",
                options["resolve_existing"],
                options["project_id"],
                "project-brain",
                options["name"],
                "Project-Brain",
                options["codex_path"],
                "/usr/bin/true",
                options["auto_push_disabled"],
                options["auto_pr_disabled"],
                options["plan"],
                options["json"],
            ]
        )
        self.assertEqual(parsed.projects_command, "add")
        self.assertTrue(parsed.resolve_existing)
        self.assertTrue(parsed.plan_only)
        self.assertTrue(parsed.json_output)

    def test_python_parser_accepts_only_fixed_local_task_command_paths(self) -> None:
        operation = load_cli_contract()["operations"]["local_task"]
        planned = build_parser().parse_args(
            [*operation["plan_command_path"], operation["options"]["json"]]
        )
        self.assertEqual(planned.tasks_command, "local-plan")
        self.assertTrue(planned.json_output)

        created = build_parser().parse_args(
            [*operation["create_command_path"], operation["options"]["json"]]
        )
        self.assertEqual(created.tasks_command, "local-create")
        self.assertFalse(hasattr(created, "plan_token"))
        self.assertFalse(hasattr(created, "command_argv"))
        self.assertEqual(operation["confirmation_schema_version"], 1)
        self.assertEqual(set(operation["options"]), {"json"})

    def test_core_error_envelope_always_has_structured_recovery_fields(self) -> None:
        payload = _error_payload(InvalidTaskError("invalid local task"))
        self.assertEqual(payload["error_code"], "invalid_task")
        self.assertIsNone(payload["field"])
        self.assertEqual(payload["constraints"], {})
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["next_action_code"], "open_diagnostics")
        self.assertRegex(payload["correlation_id"], r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
