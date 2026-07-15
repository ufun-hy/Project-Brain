from __future__ import annotations

import asyncio
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from project_brain.cli import build_parser
from project_brain.errors import ConfigurationError
from project_brain.locking import RuntimeLock
from project_brain.mcp.server import (
    DEFAULT_MCP_HOST,
    DEFAULT_MCP_PORT,
    create_mcp_server,
    validate_loopback_bind,
)
from project_brain.store import TaskStore

from tests.helpers import CoreFixture, pythonpath_env


EXPECTED_TOOLS = {
    "project_brain_system_health",
    "project_brain_projects_list",
    "project_brain_tasks_create",
    "project_brain_queue_dispatch_next",
    "project_brain_tasks_list",
    "project_brain_tasks_get",
    "project_brain_tasks_review",
    "project_brain_tasks_recovery_preview",
}


class MCPServerSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_serve_defaults_to_loopback_streamable_http(self) -> None:
        args = build_parser().parse_args(["serve"])
        self.assertEqual(args.host, DEFAULT_MCP_HOST)
        self.assertEqual(args.port, DEFAULT_MCP_PORT)
        server = create_mcp_server(self.fixture.runtime)
        self.assertEqual(server.settings.host, "127.0.0.1")
        self.assertEqual(server.settings.port, 7677)
        self.assertEqual(server.settings.streamable_http_path, "/mcp")
        self.assertTrue(server.settings.stateless_http)
        self.assertTrue(server.settings.json_response)

    def test_non_loopback_and_dns_hosts_are_rejected(self) -> None:
        for host in ("0.0.0.0", "192.168.1.10", "8.8.8.8", "localhost", "example.com"):
            with self.subTest(host=host), self.assertRaisesRegex(
                ConfigurationError, "Secure MCP Tunnel"
            ):
                validate_loopback_bind(host, 7677)
        validate_loopback_bind("127.0.0.1", 7677)
        validate_loopback_bind("::1", 7677)

    def test_tools_are_exact_allowlist_with_strict_schema_and_annotations(self) -> None:
        server = create_mcp_server(self.fixture.runtime)

        async def inspect_tools():
            return await server.list_tools()

        tools = asyncio.run(inspect_tools())
        self.assertEqual({tool.name for tool in tools}, EXPECTED_TOOLS)
        for tool in tools:
            self.assertFalse(tool.inputSchema["additionalProperties"])
            self.assertFalse(tool.annotations.openWorldHint)
            self.assertFalse(tool.annotations.destructiveHint)
            expected_read_only = tool.name not in {
                "project_brain_tasks_create",
                "project_brain_queue_dispatch_next",
                "project_brain_tasks_review",
            }
            self.assertEqual(tool.annotations.readOnlyHint, expected_read_only)
        create = next(tool for tool in tools if tool.name == "project_brain_tasks_create")
        self.assertFalse(create.inputSchema["$defs"]["AcceptanceCriterionInput"]["additionalProperties"])
        self.assertTrue(
            {
                "command",
                "argv",
                "shell",
                "cwd",
                "environment",
                "repo_path",
                "worktree_path",
                "codex_command",
            }.isdisjoint(create.inputSchema["properties"])
        )

    def test_unknown_top_level_argument_is_rejected_at_runtime(self) -> None:
        server = create_mcp_server(self.fixture.runtime)

        async def call_invalid() -> None:
            with self.assertRaisesRegex(Exception, "Extra inputs are not permitted"):
                await server.call_tool("project_brain_system_health", {"unexpected": True})

        asyncio.run(call_invalid())

    def test_fastmcp_structured_create_uses_strict_nested_models(self) -> None:
        self.fixture.add_project()
        server = create_mcp_server(self.fixture.runtime, store=self.fixture.store)
        arguments = {
            "task_id": "protocol-create",
            "project_id": "project-one",
            "dedupe_key": "protocol-create",
            "revision": 1,
            "goal": "Exercise the protocol tool boundary",
            "acceptance_criteria": [
                {"id": "documented", "text": "The behavior is documented"}
            ],
            "prompt": "Update controlled documentation only.",
        }

        async def call_create():
            return await server.call_tool("project_brain_tasks_create", arguments)

        _, structured = asyncio.run(call_create())
        self.assertEqual(structured["status"], "created")
        self.assertEqual(self.fixture.store.get_task("protocol-create")["source_type"], "mcp")
        invalid = dict(arguments)
        invalid["task_id"] = "protocol-invalid"
        invalid["dedupe_key"] = "protocol-invalid"
        invalid["acceptance_criteria"] = [
            {
                "id": "documented",
                "text": "The behavior is documented",
                "command": ["forbidden"],
            }
        ]

        async def call_nested_invalid() -> None:
            with self.assertRaisesRegex(Exception, "Extra inputs are not permitted"):
                await server.call_tool("project_brain_tasks_create", invalid)

        asyncio.run(call_nested_invalid())
        with self.assertRaises(Exception):
            self.fixture.store.get_task("protocol-invalid")


class MCPTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()
        self.source_root = Path(__file__).resolve().parents[1] / "src"
        self.repo_root = Path(__file__).resolve().parents[1]

    def tearDown(self) -> None:
        self.fixture.close()

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            return int(candidate.getsockname()[1])

    @staticmethod
    def _wait_for_port(port: int) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.1)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.05)
        raise AssertionError(f"MCP server did not listen on port {port}")

    def test_streamable_http_initialize_tools_list_and_clean_shutdown(self) -> None:
        port = self._free_port()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "project_brain",
                "--runtime-root",
                str(self.fixture.runtime.root),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=self.repo_root,
            env=pythonpath_env(self.source_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self._wait_for_port(port)

            async def inspect_transport() -> tuple[str, set[str], str]:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as streams:
                    read_stream, write_stream, _ = streams
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        tools = await session.list_tools()
                        health = await session.call_tool("project_brain_system_health", {})
                        return (
                            initialized.serverInfo.name,
                            {tool.name for tool in tools.tools},
                            health.structuredContent["status"],
                        )

            name, tool_names, health_status = asyncio.run(inspect_transport())
            self.assertEqual(name, "Project Brain")
            self.assertEqual(tool_names, EXPECTED_TOOLS)
            self.assertEqual(health_status, "ok")
        finally:
            process.terminate()
            stdout, stderr = process.communicate(timeout=10)
        self.assertIn(
            process.returncode,
            {0, -signal.SIGTERM},
            msg=f"stdout={stdout}\nstderr={stderr}",
        )
        reopened = TaskStore(self.fixture.runtime.database)
        reopened.initialize()
        self.assertEqual(reopened.schema_version(), 4)
        self.assertTrue(RuntimeLock.is_available(self.fixture.runtime.lock_file))


if __name__ == "__main__":
    unittest.main()
