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
        self.loaded: set[str] = set()
        self.bootstrap_failures: set[str] = set()
        self.bootout_failures: set[str] = set()

    def __call__(self, argv, **_kwargs):
        command = list(argv)
        self.commands.append(command)
        if len(command) == 3 and command[1] == "print":
            if command[2] in self.print_results:
                code, output = self.print_results[command[2]]
            elif command[2] in self.loaded:
                code, output = 0, "state = running"
            else:
                code, output = 1, "Could not find service; not loaded"
            return subprocess.CompletedProcess(command, code, output, "")
        if len(command) == 4 and command[1] == "bootstrap":
            label = plistlib.loads(Path(command[3]).read_bytes())["Label"]
            target = f"{command[2]}/{label}"
            if label in self.bootstrap_failures:
                return subprocess.CompletedProcess(command, 5, "", "simulated bootstrap failure")
            self.loaded.add(target)
            return subprocess.CompletedProcess(command, 0, "", "")
        if len(command) == 3 and command[1] == "bootout":
            if command[2] in self.bootout_failures:
                return subprocess.CompletedProcess(command, 5, "", "permission denied")
            if command[2] not in self.loaded:
                return subprocess.CompletedProcess(
                    command, 1, "", "Could not find service; not loaded"
                )
            self.loaded.remove(command[2])
            return subprocess.CompletedProcess(command, 0, "", "")
        if len(command) == 4 and command[1:3] == ["kickstart", "-k"]:
            if command[3] not in self.loaded:
                return subprocess.CompletedProcess(command, 1, "", "not loaded")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 64, "", "invalid launchctl argv")


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
        bootouts = [command for command in self.runner.commands if command[1] == "bootout"]
        self.assertTrue(bootouts)
        self.assertTrue(all(len(command) == 3 for command in bootouts))
        self.assertEqual(
            {command[2] for command in bootouts},
            {
                f"gui/501/{WORKER_LABEL}",
                f"gui/501/{MCP_LABEL}",
            },
        )

    def test_bootout_ignores_only_absent_services_and_propagates_other_errors(self) -> None:
        self.assertEqual(self.manager.stop()["status"], "stopped")
        self.manager.install()
        worker_target = f"gui/501/{WORKER_LABEL}"
        self.runner.bootout_failures.add(worker_target)
        with self.assertRaisesRegex(Exception, "permission denied"):
            self.manager.stop()
        self.assertIn(worker_target, self.runner.loaded)

    def test_partial_install_rolls_back_activated_services_and_is_retryable(self) -> None:
        self.runner.bootstrap_failures.add(MCP_LABEL)
        with self.assertRaisesRegex(Exception, "partially applied"):
            self.manager.install()
        self.assertEqual(self.runner.loaded, set())
        self.assertTrue(all(spec.plist_path.is_file() for spec in self.manager.specs()))

        self.runner.bootstrap_failures.clear()
        self.assertEqual(self.manager.install()["status"], "installed")
        self.assertEqual(
            self.runner.loaded,
            {f"gui/501/{WORKER_LABEL}", f"gui/501/{MCP_LABEL}"},
        )

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

        self.runner.print_results[f"{domain}/{WORKER_LABEL}"] = (
            0,
            "state = exited\nlast exit code = 0",
        )
        idle = self.manager.status()
        self.assertEqual(idle["status"], "healthy")
        self.assertEqual(idle["services"][0]["state"], "healthy")

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
