"""Unified repository, service, and MCP readiness contract for Product Shell."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any, Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .application import health_report
from .configuration import project_checks
from .executables import find_executable
from .mcp.server import DEFAULT_MCP_HOST, DEFAULT_MCP_PORT, MCP_PATH
from .runtime import RuntimePaths
from .security import redact_text
from .services import ServiceManager
from .store import TaskStore


Probe = Callable[[], tuple[bool, str]]


def github_auth_probe() -> tuple[bool, str]:
    executable = find_executable("gh")
    if executable is None:
        return False, "GitHub CLI is not installed"
    try:
        result = subprocess.run(
            [executable, "auth", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, redact_text(str(exc))[:500]
    return (
        result.returncode == 0,
        "authenticated" if result.returncode == 0 else "GitHub CLI is not authenticated",
    )


async def _probe_mcp_transport(url: str) -> str:
    async with httpx.AsyncClient(trust_env=False, timeout=3) as http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            read_stream, write_stream, _ = streams
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                return initialized.serverInfo.name


def mcp_transport_probe(
    url: str = f"http://{DEFAULT_MCP_HOST}:{DEFAULT_MCP_PORT}{MCP_PATH}",
) -> tuple[bool, str]:
    """Perform an actual MCP initialize handshake, not a TCP-only port check."""
    try:
        server_name = asyncio.run(_probe_mcp_transport(url))
    except Exception as exc:
        return False, redact_text(str(exc))[:500] or "MCP initialize failed"
    return server_name == "Project Brain", f"initialized server={server_name}"


def product_readiness_report(
    store: TaskStore,
    runtime: RuntimePaths,
    *,
    service_manager: ServiceManager | None = None,
    github_probe: Probe = github_auth_probe,
    transport_probe: Probe = mcp_transport_probe,
) -> dict[str, Any]:
    """Combine all blocking Product Shell prerequisites in one typed response."""
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if passed else "failed",
                "detail": detail,
                "blocking": True,
            }
        )

    core = health_report(store, runtime)
    for item in core["checks"]:
        add(f"core:{item['name']}", item["status"] == "passed", item["detail"])

    projects = store.list_projects()
    add("registered_projects", bool(projects), f"count={len(projects)}")
    project_reports = []
    for project in projects:
        report = project_checks(project, runtime)
        project_reports.append(report)
        for item in report["checks"]:
            add(
                f"project:{project['project_id']}:{item['name']}",
                bool(item["passed"]),
                "passed" if item["passed"] else "failed",
            )

    gh_passed, gh_detail = github_probe()
    add("github_auth", gh_passed, gh_detail)

    manager = service_manager or ServiceManager(runtime)
    service_status = manager.status()
    by_name = {item["name"]: item for item in service_status["services"]}
    worker_state = by_name.get("worker", {}).get("state", "not_installed")
    mcp_state = by_name.get("mcp", {}).get("state", "not_installed")
    add("worker_service", worker_state in {"healthy", "running"}, worker_state)
    add("mcp_service", mcp_state == "running", mcp_state)
    add(
        "managed_helper",
        bool(service_status.get("helper_executable")),
        "executable" if service_status.get("helper_executable") else "missing or not executable",
    )

    if mcp_state == "running":
        transport_passed, transport_detail = transport_probe()
    else:
        transport_passed, transport_detail = False, "MCP service is not running"
    add("mcp_transport", transport_passed, transport_detail)

    ready = all(item["status"] == "passed" for item in checks)
    return {
        "status": "healthy" if ready else "unhealthy",
        "ready": ready,
        "checks": checks,
        "services": service_status,
        "projects": project_reports,
    }
