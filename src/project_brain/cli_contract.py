"""Versioned App/Core CLI contract loaded from packaged immutable data."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

RESOURCE_NAME = "cli_contract.json"


def cli_contract_bytes() -> bytes:
    return files("project_brain").joinpath(RESOURCE_NAME).read_bytes()


def cli_contract_sha256() -> str:
    return hashlib.sha256(cli_contract_bytes()).hexdigest()


def load_cli_contract() -> dict[str, Any]:
    value = json.loads(cli_contract_bytes())
    if value.get("schema_version") != 1:
        raise RuntimeError("unsupported Core CLI contract schema")
    if value.get("contract_version") != "1.2.0":
        raise RuntimeError("unsupported Core CLI contract version")
    local_task = value.get("operations", {}).get("local_task", {})
    if (
        local_task.get("request_schema_version") != 1
        or local_task.get("confirmation_schema_version") != 1
        or local_task.get("transport") != "stdin_json"
        or local_task.get("plan_command_path") != ["tasks", "local-plan"]
        or local_task.get("create_command_path") != ["tasks", "local-create"]
        or local_task.get("options") != {"json": "--json"}
    ):
        raise RuntimeError("invalid local task stdin contract")
    onboarding = value.get("operations", {}).get("native_onboarding", {})
    if onboarding.get("command_path") != ["projects", "add"]:
        raise RuntimeError("invalid native onboarding command path")
    options = onboarding.get("options", {})
    required = {
        "resolve_existing",
        "project_id",
        "name",
        "default_branch",
        "codex_path",
        "verification_file",
        "auto_push_enabled",
        "auto_push_disabled",
        "auto_pr_enabled",
        "auto_pr_disabled",
        "plan",
        "non_interactive",
        "plan_token",
        "json",
    }
    if set(options) != required:
        raise RuntimeError("incomplete native onboarding option contract")
    if any(
        not isinstance(item, str) or not item.startswith("--")
        for item in options.values()
    ):
        raise RuntimeError("invalid native onboarding option contract")
    return value
