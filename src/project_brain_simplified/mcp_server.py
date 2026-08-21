from __future__ import annotations

from pathlib import Path

from .runtime import RuntimePaths
from .service import Service

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7677
SUPPORTED_HOSTS = {"127.0.0.1", "::1"}


def validate_loopback(host: str, port: int) -> None:
    if host not in SUPPORTED_HOSTS:
        raise ValueError("MCP host must be 127.0.0.1 or ::1")
    if isinstance(port, bool) or not 1 <= int(port) <= 65535:
        raise ValueError("MCP port must be 1-65535")


def create_server(runtime: RuntimePaths, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    validate_loopback(host, port)
    service = Service(runtime)
    if host == "127.0.0.1":
        host_header = "127.0.0.1:*"
        allowed_origins = ["http://127.0.0.1:*"]
    else:
        host_header = "[::1]:*"
        allowed_origins = ["http://[::1]:*"]
    server = FastMCP(
        "Project Brain Simplified",
        instructions=(
            "Thin personal bridge from ChatGPT to local Codex. ChatGPT owns planning and final review. "
            "The bridge exposes project memory, starts bounded Codex worktree tasks, and returns code/test evidence."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host_header],
            allowed_origins=allowed_origins,
        ),
    )

    @server.tool(name="project_brain_system_health")
    def system_health() -> dict:
        return service.health()

    @server.tool(name="project_brain_projects_list")
    def projects_list() -> dict:
        return {"projects": service.projects_list()}

    @server.tool(name="project_brain_project_context_get")
    def project_context_get(project_id: str) -> dict:
        return service.project_context_get(project_id)

    @server.tool(name="project_brain_task_run")
    def task_run(
        project_id: str,
        goal: str,
        prompt: str,
        ponytail_mode: str | None = None,
    ) -> dict:
        return service.task_run(
            project_id=project_id,
            goal=goal,
            prompt=prompt,
            ponytail_mode=ponytail_mode,
        )

    @server.tool(name="project_brain_tasks_list")
    def tasks_list(project_id: str | None = None, limit: int = 20) -> dict:
        return {"tasks": service.tasks_list(project_id=project_id, limit=limit)}

    @server.tool(name="project_brain_tasks_get")
    def tasks_get(task_id: str) -> dict:
        return service.tasks_get(task_id)

    return server


def run_server(runtime_root: str | Path | None = None, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    runtime = RuntimePaths.from_value(runtime_root).ensure()
    create_server(runtime, host=host, port=port).run(transport="streamable-http")
