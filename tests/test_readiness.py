from __future__ import annotations

import unittest
from typing import Any

from project_brain.readiness import product_readiness_report

from tests.helpers import CoreFixture, create_remote_clone, executable_script


class FakeServiceManager:
    def __init__(
        self,
        *,
        worker_state: str = "healthy",
        worker_exit: int | None = 0,
        mcp_state: str = "running",
        helper_executable: bool = True,
    ) -> None:
        self.worker_state = worker_state
        self.worker_exit = worker_exit
        self.mcp_state = mcp_state
        self.helper_executable = helper_executable

    def status(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "helper_executable": self.helper_executable,
            "services": [
                {
                    "name": "worker",
                    "label": "com.projectbrain.worker",
                    "state": self.worker_state,
                    "installed": True,
                    "last_exit_code": self.worker_exit,
                },
                {
                    "name": "mcp",
                    "label": "com.projectbrain.mcp",
                    "state": self.mcp_state,
                    "installed": True,
                    "last_exit_code": None,
                },
            ],
        }


class ProductReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.repo, self.remote = create_remote_clone(self.fixture.root, "readiness")
        self.codex = executable_script(self.fixture.root / "codex", "print('ok')\n")
        self.fixture.add_project(
            repo_path=str(self.repo),
            remote_url=str(self.remote),
            codex_command=[str(self.codex)],
            auto_push=False,
            auto_pr=False,
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def report(
        self,
        manager: FakeServiceManager | None = None,
        *,
        github: bool = True,
        transport: bool = True,
    ) -> dict[str, Any]:
        return product_readiness_report(
            self.fixture.store,
            self.fixture.runtime,
            service_manager=manager or FakeServiceManager(),
            github_probe=lambda: (github, "authenticated" if github else "not authenticated"),
            transport_probe=lambda: (transport, "initialized" if transport else "no response"),
        )

    @staticmethod
    def check(report: dict[str, Any], name: str) -> dict[str, Any]:
        return next(item for item in report["checks"] if item["name"] == name)

    def test_ready_requires_every_project_service_transport_and_github_check(self) -> None:
        report = self.report()
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "healthy")
        names = {item["name"] for item in report["checks"]}
        self.assertIn("project:project-one:origin", names)
        self.assertIn("github_auth", names)
        self.assertIn("worker_service", names)
        self.assertIn("mcp_transport", names)

    def test_worker_clean_exit_is_healthy_but_nonzero_exit_blocks(self) -> None:
        clean = self.report(FakeServiceManager(worker_state="healthy", worker_exit=0))
        self.assertTrue(self.check(clean, "worker_service")["status"] == "passed")

        failed = self.report(FakeServiceManager(worker_state="unhealthy", worker_exit=78))
        self.assertFalse(failed["ready"])
        self.assertEqual(self.check(failed, "worker_service")["detail"], "unhealthy")

    def test_mcp_must_be_running_and_answer_initialize(self) -> None:
        no_response = self.report(transport=False)
        self.assertFalse(no_response["ready"])
        self.assertEqual(self.check(no_response, "mcp_transport")["status"], "failed")

        calls = 0

        def unexpected_probe() -> tuple[bool, str]:
            nonlocal calls
            calls += 1
            return True, "unexpected"

        stopped = product_readiness_report(
            self.fixture.store,
            self.fixture.runtime,
            service_manager=FakeServiceManager(mcp_state="stopped"),
            github_probe=lambda: (True, "authenticated"),
            transport_probe=unexpected_probe,
        )
        self.assertFalse(stopped["ready"])
        self.assertEqual(calls, 0)

    def test_github_unauthenticated_blocks_readiness(self) -> None:
        report = self.report(github=False)
        self.assertFalse(report["ready"])
        self.assertEqual(self.check(report, "github_auth")["status"], "failed")

    def test_non_executable_codex_file_blocks_health_and_project_checks(self) -> None:
        self.codex.chmod(0o644)
        report = self.report()
        self.assertFalse(report["ready"])
        self.assertEqual(self.check(report, "core:codex:project-one")["status"], "failed")
        self.assertEqual(
            self.check(report, "project:project-one:codex")["status"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
