from __future__ import annotations

import io
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from project_brain.cli import main
from project_brain.runtime import RuntimePaths
from project_brain.services import ServiceManager
from project_brain.store import TaskStore

from tests.helpers import create_remote_clone


class StatefulLaunchctl:
    def __init__(self) -> None:
        self.loaded: set[str] = set()
        self.commands: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        arguments = list(argv)
        self.commands.append(arguments)
        action = arguments[1]
        if action == "bootstrap" and len(arguments) == 4:
            label = plistlib.loads(Path(arguments[3]).read_bytes())["Label"]
            self.loaded.add(f"{arguments[2]}/{label}")
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if action == "bootout" and len(arguments) == 3:
            if arguments[2] not in self.loaded:
                return subprocess.CompletedProcess(
                    arguments, 1, "", "Could not find service; not loaded"
                )
            self.loaded.remove(arguments[2])
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if action == "print" and len(arguments) == 3:
            if arguments[2] in self.loaded:
                return subprocess.CompletedProcess(arguments, 0, "state = running", "")
            return subprocess.CompletedProcess(
                arguments, 1, "", "Could not find service; not loaded"
            )
        if action == "kickstart" and len(arguments) == 4 and arguments[2] == "-k":
            if arguments[3] in self.loaded:
                return subprocess.CompletedProcess(arguments, 0, "", "")
            return subprocess.CompletedProcess(arguments, 1, "", "not loaded")
        return subprocess.CompletedProcess(arguments, 64, "", "invalid launchctl argv")


class ProductShellFixtureIntegrationTests(unittest.TestCase):
    def test_first_run_task_observation_restart_and_data_preserving_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            repo, _remote = create_remote_clone(root, "product-shell")

            def invoke(*arguments: str) -> tuple[int, object]:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(["--runtime-root", str(runtime), *arguments])
                return code, json.loads(stdout.getvalue())

            self.assertEqual(invoke("init", "--json")[0], 0)
            code, plan = invoke(
                "projects", "add", str(repo), "--project-id", "fixture",
                "--codex-path", sys.executable, "--no-auto-push", "--no-auto-pr",
                "--plan", "--json",
            )
            self.assertEqual(code, 0)
            self.assertEqual(plan["status"], "planned")
            self.assertEqual(invoke(
                "projects", "add", str(repo), "--project-id", "fixture",
                "--codex-path", sys.executable, "--no-auto-push", "--no-auto-pr",
                "--non-interactive", "--plan-token", plan["plan"]["plan_token"], "--json",
            )[0], 0)

            helper = root / "project-brain"
            helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            helper.chmod(0o755)
            launchctl = StatefulLaunchctl()
            services = ServiceManager(
                RuntimePaths.from_value(runtime),
                helper_path=helper,
                launch_agents_dir=root / "LaunchAgents",
                runner=launchctl,
                uid=501,
            )
            services.install()
            self.assertEqual(services.status()["status"], "healthy")

            task_file = root / "task.json"
            task_file.write_text(
                json.dumps(
                    {
                        "task_id": "fixture-task",
                        "project_id": "fixture",
                        "dedupe_key": "fixture-task",
                        "revision": 1,
                        "source_type": "fixture",
                        "goal": "Exercise the Product Shell fixture flow",
                        "task_type": "write_files",
                        "acceptance_criteria": [],
                        "payload": {
                            "files": [
                                {"path": "product-shell.txt", "content": "fixture\n"}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                invoke("tasks", "enqueue", "--file", str(task_file), "--json")[1]["status"],
                "created",
            )
            self.assertEqual(invoke("tasks", "list", "--json")[1][0]["status"], "pending")
            self.assertEqual(invoke("apply", "--json")[0], 0)
            observed = invoke("tasks", "show", "fixture-task", "--json")[1]
            self.assertEqual(observed["status"], "awaiting_review", observed)
            self.assertIsNotNone(observed["commit"])

            services.stop()
            self.assertEqual(services.status()["status"], "stopped")
            services.start()
            self.assertEqual(services.status()["status"], "healthy")
            reopened = TaskStore(runtime / "project-brain.db")
            reopened.initialize()
            self.assertEqual(reopened.get_task("fixture-task")["status"], "awaiting_review")
            database_before = (runtime / "project-brain.db").read_bytes()
            services.stop()
            result = services.uninstall()
            self.assertTrue(result["runtime_preserved"])
            self.assertEqual((runtime / "project-brain.db").read_bytes(), database_before)
            bootouts = [command for command in launchctl.commands if command[1] == "bootout"]
            self.assertTrue(bootouts)
            self.assertTrue(all(len(command) == 3 for command in bootouts))


if __name__ == "__main__":
    unittest.main()
