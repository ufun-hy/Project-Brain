"""Fixed real-project acceptance task planning for Product Shell RC1."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .acceptance import ExternalAcceptanceManager
from .errors import InvalidTaskError, StateConflictError
from .models import CanonicalTask
from .store import TaskStore


ACCEPTANCE_DOCUMENT_PATH = "docs/project-brain-acceptance.md"
ACCEPTANCE_DEDUPE_KEY = "project-brain-rc1-acceptance"
ACCEPTANCE_SOURCE_TYPE = "product_shell_acceptance"
PLAN_TOKEN_VERSION = 1


def _token(plan: dict[str, Any]) -> str:
    fields = {
        "version": PLAN_TOKEN_VERSION,
        "project_id": plan["project_id"],
        "project_config_revision": plan["project_config_revision"],
        "project_config_sha256": plan["project_config_sha256"],
        "acceptance_run_id": plan["acceptance_run_id"],
        "acceptance_verified_at": plan["acceptance_verified_at"],
        "task_id": plan["task_id"],
        "dedupe_key": plan["dedupe_key"],
        "revision": plan["revision"],
        "changed_files": plan["changed_files"],
    }
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"v{PLAN_TOKEN_VERSION}:{hashlib.sha256(canonical.encode()).hexdigest()}"


def acceptance_task_plan(store: TaskStore, project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    if not project["registered"]:
        raise InvalidTaskError(f"Unregistered project: {project_id}")
    if not project["accepting_tasks"]:
        raise InvalidTaskError(f"Project is paused and not accepting tasks: {project_id}")
    if not project["auto_push"] or not project["auto_pr"]:
        raise InvalidTaskError(
            "Real-project acceptance requires auto-push and Draft PR creation for the project"
        )
    passed = ExternalAcceptanceManager(store).status()["last_passed"]
    if passed is None:
        raise StateConflictError(
            "A real MCP external acceptance probe must pass before creating this task"
        )
    task_id = f"rc1-{passed['run_id']}"
    with store.connect() as connection:
        existing = connection.execute(
            "SELECT revision FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        latest = connection.execute(
            "SELECT MAX(revision) FROM tasks WHERE project_id = ? AND dedupe_key = ?",
            (project_id, ACCEPTANCE_DEDUPE_KEY),
        ).fetchone()
    revision = int(existing["revision"]) if existing is not None else int(latest[0] or 0) + 1
    plan = {
        "status": "planned",
        "project_id": project_id,
        "project_name": project["name"],
        "project_config_revision": project["config_revision"],
        "project_config_sha256": project["config_sha256"],
        "acceptance_run_id": passed["run_id"],
        "acceptance_verified_at": passed["verified_at"],
        "project_brain_version": passed["core_version"],
        "task_id": task_id,
        "dedupe_key": ACCEPTANCE_DEDUPE_KEY,
        "revision": revision,
        "changed_files": [ACCEPTANCE_DOCUMENT_PATH],
        "effect": (
            "Create or update one controlled acceptance document in an isolated worktree, "
            "run verification, push a task branch, and create a Draft PR. Never merge."
        ),
    }
    return {**plan, "plan_token": _token(plan)}


def create_acceptance_task(
    store: TaskStore,
    *,
    project_id: str,
    plan_token: str | None,
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    plan = acceptance_task_plan(store, project_id)
    if not plan_token or not hmac.compare_digest(plan_token, _token(plan)):
        raise StateConflictError(
            "Acceptance task state changed after preview; refresh and review the new plan"
        )
    content = (
        "# Project Brain External Acceptance\n\n"
        f"- Acceptance time: {plan['acceptance_verified_at']}\n"
        f"- Project Brain version: {plan['project_brain_version']}\n"
        f"- Acceptance run ID: {plan['acceptance_run_id']}\n"
    )
    prompt = (
        f"Update only `{ACCEPTANCE_DOCUMENT_PATH}` to exactly the UTF-8 content below. "
        "Do not modify, delete, or rename any other file. Do not change Git configuration.\n\n"
        f"{content}"
    )
    canonical = CanonicalTask(
        task_id=plan["task_id"],
        project_id=project_id,
        dedupe_key=ACCEPTANCE_DEDUPE_KEY,
        revision=plan["revision"],
        source_type=ACCEPTANCE_SOURCE_TYPE,
        goal="Record the verified Project Brain RC1 acceptance in one controlled document",
        task_type="codex",
        acceptance_criteria=[
            {
                "id": "rc1-acceptance-document",
                "text": (
                    "Only docs/project-brain-acceptance.md changes and exactly records "
                    "the bound external acceptance run"
                ),
            }
        ],
        payload={
            "prompt": prompt,
            "acceptance_run_id": plan["acceptance_run_id"],
            "acceptance_document_path": ACCEPTANCE_DOCUMENT_PATH,
            "acceptance_document_content": content,
        },
    )
    task, created = store.insert_task(canonical)
    return task, created, plan
