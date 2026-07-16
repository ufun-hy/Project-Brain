from __future__ import annotations

import io
import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from project_brain.cli import main
from project_brain.executables import LAUNCHD_TOOL_PATH
from project_brain.runtime import RuntimePaths
from project_brain.services import LAUNCHCTL, MCP_LABEL, WORKER_LABEL, ServiceManager


class FakeLaunchctl:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.print_results: dict[str, tuple[int, str]] = {}

    def __call__(self, argv, **_kwargs):
        command = list(argv)
        self.commands.append(command)
        if len(command) >= 3 and command[1] == "print":
            code, output = self.print_results.get(command[2], (1, "not loaded"))
            return subprocess.CompletedProcess(command, code, output, "")
        return subprocess.CompletedProcess(command, 0, "", "")


class ServiceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = RuntimePaths.from_value(self.root / "runtime")
        self.launch_agents = self.root / "LaunchAgents"
        self.helper = self.root / "project-brain"
        self.helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.helper.chmod(0o755)
        self.runner = FakeLaunchctl()
        self.manager = ServiceManager(
            self.runtime,
            helper_path=self.helper,
            launch_agents_dir=self.launch_agents,
            runner=self.runner,
            uid=501,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plan_is_read_only_and_contains_only_fixed_absolute_argv(self) -> None:
        plan = self.manager.plan()
        self.assertEqual(plan["status"], "planned")
        self.assertFalse(self.runtime.root.exists())
        self.assertFalse(self.launch_agents.exists())
        self.assertEqual(self.runner.commands, [])
        for service in plan["services"]:
            argv = service["program_arguments"]
            self.assertEqual(argv[0], str(self.helper.resolve()))
            self.assertTrue(Path(argv[0]).is_absolute())
            self.assertNotIn("sh", argv)
            self.assertNotIn("zsh", argv)

    def test_install_and_reinstall_are_idempotent_private_and_shell_free(self) -> None:
        first = self.manager.install()
        rendered = {
            spec.name: spec.plist_path.read_bytes() for spec in self.manager.specs()
        }
        second = self.manager.install()
        self.assertEqual(first["status"], "installed")
        self.assertEqual(second["status"], "installed")
        for spec in self.manager.specs():
            self.assertEqual(spec.plist_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(spec.plist_path.read_bytes(), rendered[spec.name])
            value = plistlib.loads(rendered[spec.name])
            self.assertEqual(value["ProgramArguments"], list(spec.program_arguments))
            self.assertEqual(value["EnvironmentVariables"], {"PATH": LAUNCHD_TOOL_PATH})
            self.assertTrue(all(isinstance(item, str) for item in value["ProgramArguments"]))
        self.assertTrue(all(command[0] == LAUNCHCTL for command in self.runner.commands))
        self.assertTrue(all("-lc" not in command for command in self.runner.commands))

    def test_stop_and_uninstall_preserve_runtime_database_and_history(self) -> None:
        self.manager.install()
        database = self.runtime.database
        database.write_text("preserve-me", encoding="utf-8")
        self.assertEqual(self.manager.stop()["status"], "stopped")
        result = self.manager.uninstall()
        self.assertEqual(result["status"], "uninstalled")
        self.assertTrue(result["runtime_preserved"])
        self.assertEqual(database.read_text(encoding="utf-8"), "preserve-me")
        self.assertTrue(all(not spec.plist_path.exists() for spec in self.manager.specs()))

    def test_status_distinguishes_running_stopped_and_unhealthy(self) -> None:
        self.manager.install()
        domain = self.manager.domain
        self.runner.print_results[f"{domain}/{WORKER_LABEL}"] = (0, "state = running")
        self.runner.print_results[f"{domain}/{MCP_LABEL}"] = (0, "state = running")
        self.assertEqual(self.manager.status()["status"], "healthy")

        self.runner.print_results[f"{domain}/{WORKER_LABEL}"] = (1, "not loaded")
        self.assertEqual(self.manager.status()["status"], "stopped")

        self.runner.print_results[f"{domain}/{WORKER_LABEL}"] = (
            0,
            "state = exited\nlast exit code = 78",
        )
        self.assertEqual(self.manager.status()["status"], "unhealthy")

    def test_cli_service_plan_does_not_initialize_runtime(self) -> None:
        runtime = self.root / "cli-runtime"
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--runtime-root",
                    str(runtime),
                    "service",
                    "plan",
                    "--helper-path",
                    str(self.helper),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "planned")
        self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
