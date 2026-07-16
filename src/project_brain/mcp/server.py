"""FastMCP Streamable HTTP server wiring."""

from __future__ import annotations

import ipaddress

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from project_brain.errors import ConfigurationError
from project_brain.runtime import RuntimePaths
from project_brain.store import TaskStore

from .dispatch import OneShotDispatcher
from .tools import MCPAdapterService, register_tools


DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 7677
MCP_PATH = "/mcp"


def validate_loopback_bind(host: str, port: int) -> None:
    """Reject DNS names, wildcards, and non-loopback listeners for the no-auth MVP."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ConfigurationError(
            "MCP host must be the loopback IP 127.0.0.1 or ::1; use OpenAI "
            "Secure MCP Tunnel for remote access"
        ) from exc
    if str(address) not in {"127.0.0.1", "::1"}:
        raise ConfigurationError(
            "Unauthenticated MCP may bind only to 127.0.0.1 or ::1; use OpenAI "
            "Secure MCP Tunnel for remote access"
        )
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigurationError("MCP port must be an integer from 1 to 65535")


def create_mcp_server(
    runtime: RuntimePaths,
    *,
    host: str = DEFAULT_MCP_HOST,
    port: int = DEFAULT_MCP_PORT,
    store: TaskStore | None = None,
    dispatcher: OneShotDispatcher | None = None,
) -> FastMCP:
    """Create the stable loopback Streamable HTTP MCP server."""
    validate_loopback_bind(host, port)
    active_store = store or TaskStore(runtime.database)
    active_store.initialize()
    service = MCPAdapterService(
        active_store,
        runtime,
        dispatcher=dispatcher,
    )
    host_header = "127.0.0.1:*" if host == "127.0.0.1" else "[::1]:*"
    server = FastMCP(
        "Project Brain",
        instructions=(
            "Controlled Project Brain task adapter. It exposes no shell, arbitrary "
            "filesystem, recovery resolution, cleanup, acceptance, or merge tools."
        ),
        host=host,
        port=port,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host_header],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
    )
    register_tools(server, service)
    return server


def run_mcp_server(
    runtime: RuntimePaths,
    *,
    host: str = DEFAULT_MCP_HOST,
    port: int = DEFAULT_MCP_PORT,
) -> None:
    """Load registered projects and run the long-lived Streamable HTTP server."""
    validate_loopback_bind(host, port)
    store = TaskStore(runtime.database)
    store.initialize()
    server = create_mcp_server(runtime, host=host, port=port, store=store)
    server.run(transport="streamable-http")
