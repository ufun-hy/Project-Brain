"""Allowlisted MCP tool schemas and Core application adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Literal, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from project_brain.acceptance import ExternalAcceptanceManager
from project_brain import __version__
from project_brain.errors import (
    AlreadyRunningError,
    InvalidTaskError,
    RecoveryError,
    StateTransitionError,
)
from project_brain.ingress import TaskImporter
from project_brain.locking import RuntimeLock
from project_brain.models import TaskStatus, parse_timestamp
from project_brain.recovery import RecoveryManager
from project_brain.runtime import RuntimePaths
from project_brain.security import contains_known_secret
from project_brain.store import TaskStore
from project_brain.worktrees import WorktreeManager

from .dispatch import OneShotDispatcher
from .presenters import (
    bounded_text,
    health_view,
    projects_view,
    task_detail_view,
    task_summary,
    tasks_list_view,
)


StableId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
PromptText = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
TimestampText = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ShaText = Annotated[str, StringConstraints(min_length=7, max_length=128)]
ReasonText = Annotated[str, StringConstraints(min_length=1, max_length=500)]
AcceptanceChallenge = Annotated[
    str,
    StringConstraints(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]{32,128}$",
    ),
]
Limit = Annotated[int, Field(ge=1, le=100)]

FORBIDDEN_CONTROL_FIELDS = {
    "argv",
    "codex_command",
    "command",
    "cwd",
    "environment",
    "repo_path",
    "shell",
    "worktree_path",
}


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AcceptanceCriterionInput(StrictInput):
    id: StableId
    text: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
    verification_id: StableId | None = None


class ReviewFindingInput(StrictInput):
    severity: Literal["blocker", "critical", "major", "minor", "nit"]
    file: Annotated[str, StringConstraints(min_length=1, max_length=1_000)] | None = None
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=4_000)]
    requirement: Annotated[str, StringConstraints(min_length=1, max_length=4_000)]


class TaskCreateInput(StrictInput):
    task_id: StableId
    project_id: StableId
    dedupe_key: StableId
    revision: Annotated[int, Field(ge=1, le=1_000_000)]
    goal: ShortText
    acceptance_criteria: Annotated[list[AcceptanceCriterionInput], Field(max_length=50)]
    prompt: PromptText
    task_type: Literal["codex"] = "codex"
    expires_at: TimestampText | None = None
    supersedes: StableId | None = None


class TaskReviewInput(StrictInput):
    task_id: StableId
    head_sha: ShaText
    verdict: Literal["approved", "needs_changes"]
    findings: Annotated[list[ReviewFindingInput], Field(max_length=50)]


def reject_forbidden_control_fields(value: Any, *, path: str = "input") -> None:
    """Reject execution/path control fields at every nesting depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_CONTROL_FIELDS:
                raise InvalidTaskError(f"Forbidden MCP control field at {path}.{key}: {key}")
            reject_forbidden_control_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_forbidden_control_fields(item, path=f"{path}[{index}]")


T = TypeVar("T")


def _error_code(exc: Exception) -> str:
    if isinstance(exc, AlreadyRunningError):
        return "already_running"
    if isinstance(exc, RecoveryError):
        return "recovery_blocked"
    if isinstance(exc, StateTransitionError):
        return "state_conflict"
    if isinstance(exc, (InvalidTaskError, ValidationError, ValueError)):
        message = str(exc).lower()
        if any(marker in message for marker in ("unknown task", "unregistered project", "unknown project")):
            return "not_found"
        return "validation"
    return "internal"


def _guard(call: Callable[[], T]) -> T | dict[str, Any]:
    try:
        return call()
    except Exception as exc:
        code = _error_code(exc)
        if code == "internal":
            message = "Project Brain could not complete the controlled MCP operation"
        else:
            message = bounded_text(exc, limit=2_000) or code
        return {"status": "error", "code": code, "message": message}


class MCPAdapterService:
    """Narrow application service called by all MCP tool functions."""

    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimePaths,
        *,
        dispatcher: OneShotDispatcher | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.dispatcher = dispatcher or OneShotDispatcher(store, runtime)

    def system_health(self) -> dict[str, Any]:
        return _guard(
            lambda: {
                "status": "ok",
                "code": "ok",
                "data": health_view(self.store, self.runtime),
            }
        )  # type: ignore[return-value]

    def projects_list(self) -> dict[str, Any]:
        return _guard(
            lambda: {
                "status": "ok",
                "code": "ok",
                "projects": projects_view(self.store),
            }
        )  # type: ignore[return-value]

    def tasks_create(self, value: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            reject_forbidden_control_fields(value)
            request = TaskCreateInput.model_validate(value)
            request_value = request.model_dump(exclude_none=True)
            if contains_known_secret(request_value):
                raise InvalidTaskError("MCP task contains a credential-like value")
            expiry = parse_timestamp(request.expires_at)
            if expiry is not None and expiry <= datetime.now(timezone.utc):
                raise InvalidTaskError("MCP task expires_at must be in the future")
            canonical = {
                "task_id": request.task_id,
                "project_id": request.project_id,
                "dedupe_key": request.dedupe_key,
                "revision": request.revision,
                "source_type": "mcp",
                "goal": request.goal,
                "task_type": "codex",
                "acceptance_criteria": [
                    item.model_dump(exclude_none=True) for item in request.acceptance_criteria
                ],
                "payload": {"prompt": request.prompt},
                "expires_at": request.expires_at,
                "supersedes": request.supersedes,
            }
            task, created = TaskImporter(self.store).import_value(canonical)
            if not created:
                self.store.record_event(
                    task_id=task["task_id"],
                    event_type="mcp_task_create_requested",
                    payload={
                        "requested_task_id": request.task_id,
                        "outcome": "duplicate",
                    },
                )
            projects = {item["project_id"]: item for item in self.store.list_projects()}
            summary = task_summary(task, projects)
            return {
                "status": "created" if created else "duplicate",
                "code": "ok",
                "task": summary,
                "next_action": "Call project_brain_queue_dispatch_next to process the queue.",
            }

        return _guard(operation)  # type: ignore[return-value]

    def queue_dispatch_next(self, *, reason: str | None = None) -> dict[str, Any]:
        return _guard(lambda: self.dispatcher.dispatch(reason=reason))  # type: ignore[return-value]

    def tasks_list(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            bounded_limit = max(1, min(int(limit), 100))
            if project_id is not None:
                self.store.get_project(project_id)
            if status is not None:
                TaskStatus(status)
            tasks = tasks_list_view(
                self.store,
                project_id=project_id,
                status=status,
                limit=bounded_limit,
            )
            return {
                "status": "ok",
                "code": "ok",
                "tasks": tasks,
                "limit": bounded_limit,
            }

        return _guard(operation)  # type: ignore[return-value]

    def tasks_get(self, *, task_id: str, recent_event_limit: int = 20) -> dict[str, Any]:
        return _guard(
            lambda: {
                "status": "ok",
                "code": "ok",
                "data": task_detail_view(
                    self.store,
                    task_id,
                    recent_event_limit=max(1, min(int(recent_event_limit), 100)),
                ),
            }
        )  # type: ignore[return-value]

    def tasks_review(self, value: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            reject_forbidden_control_fields(value)
            request = TaskReviewInput.model_validate(value)
            request_value = request.model_dump(exclude_none=True)
            if contains_known_secret(request_value):
                raise InvalidTaskError("MCP review contains a credential-like value")
            with RuntimeLock(self.runtime.lock_file):
                applied = self.store.apply_review_verdict(
                    request.task_id,
                    verdict=request.verdict,
                    head_sha=request.head_sha,
                    findings=[item.model_dump(exclude_none=True) for item in request.findings],
                )
            projects = {item["project_id"]: item for item in self.store.list_projects()}
            review = applied["review"]
            return {
                "status": applied["task"]["status"],
                "code": "ok",
                "task": task_summary(applied["task"], projects),
                "review": {
                    "review_id": review["review_id"],
                    "head_sha": review["head_sha"],
                    "verdict": review["verdict"],
                    "finding_count": len(review.get("findings", [])),
                    "created_at": review["created_at"],
                },
                "next_action": (
                    "Call project_brain_queue_dispatch_next for the requested revision."
                    if request.verdict == "needs_changes"
                    else "Await explicit user merge authorization; Project Brain will not merge."
                ),
            }

        return _guard(operation)  # type: ignore[return-value]

    def tasks_recovery_preview(self, *, task_id: str) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            manager = RecoveryManager(
                self.store, WorktreeManager(self.store, self.runtime)
            )
            task = self.store.get_task(task_id)
            action = manager.reconcile(task_id, execute=False)[0]
            identity = manager.agent_identity_preview(task_id)
            blocker = next(
                (
                    item
                    for item in self.store.list_claim_blocking_tasks()
                    if item["task_id"] == task_id
                ),
                None,
            )
            action_name = action.get("action")
            if task["status"] == TaskStatus.RECOVERY_BLOCKED.value or action_name == "would_recovery_block":
                recommended = (
                    f"Run project-brain tasks recover {task_id} --dry-run --json locally, "
                    "inspect the agent identity, then choose an explicit operator resolution."
                )
            elif action_name == "unchanged" and identity["identity_state"] in {
                "starting",
                "verified_alive",
            }:
                recommended = "Wait for the active worker and inspect project-brain health locally."
            elif action_name == "would_recover":
                recommended = "A local project-brain apply --json may perform this safe recovery."
            else:
                recommended = "No recovery write is recommended for the current task state."
            return {
                "status": "ok",
                "code": "ok",
                "task_id": task_id,
                "task_status": task["status"],
                "dry_run_action": {
                    "action": action.get("action"),
                    "from_status": action.get("from_status"),
                    "to_status": action.get("to_status"),
                    "phase": action.get("phase"),
                    "reason": bounded_text(action.get("reason"), limit=1_000),
                },
                "agent_identity": identity,
                "claim_blocker": {
                    "blocked": blocker is not None,
                    "status": blocker.get("status") if blocker else None,
                    "attempt_count": blocker.get("attempt_count") if blocker else None,
                    "reason": bounded_text(blocker.get("last_error"), limit=1_000) if blocker else None,
                },
                "recommended_cli_action": recommended,
            }

        return _guard(operation)  # type: ignore[return-value]


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
CREATE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
REVIEW_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
DISPATCH_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
ACCEPTANCE_PROBE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


def register_tools(mcp: FastMCP, service: MCPAdapterService) -> None:
    """Register the stable Project Brain MCP surface."""

    acceptance = ExternalAcceptanceManager(service.store)

    @mcp.tool(
        name="project_brain_system_health",
        description="Inspect bounded Project Brain Core and registered-project health.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def project_brain_system_health() -> dict[str, Any]:
        return service.system_health()

    @mcp.tool(
        name="project_brain_projects_list",
        description="List registered Project Brain projects without local paths or commands.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def project_brain_projects_list() -> dict[str, Any]:
        return service.projects_list()

    @mcp.tool(
        name="project_brain_tasks_create",
        description="Create an idempotent canonical Codex task through the controlled MCP ingress.",
        annotations=CREATE_WRITE,
        structured_output=True,
    )
    def project_brain_tasks_create(
        task_id: StableId,
        project_id: StableId,
        dedupe_key: StableId,
        revision: Annotated[int, Field(ge=1, le=1_000_000)],
        goal: ShortText,
        acceptance_criteria: Annotated[list[AcceptanceCriterionInput], Field(max_length=50)],
        prompt: PromptText,
        task_type: Literal["codex"] = "codex",
        expires_at: TimestampText | None = None,
        supersedes: StableId | None = None,
    ) -> dict[str, Any]:
        return service.tasks_create(
            {
                "task_id": task_id,
                "project_id": project_id,
                "dedupe_key": dedupe_key,
                "revision": revision,
                "goal": goal,
                "acceptance_criteria": [item.model_dump(exclude_none=True) for item in acceptance_criteria],
                "prompt": prompt,
                "task_type": task_type,
                "expires_at": expires_at,
                "supersedes": supersedes,
            }
        )

    @mcp.tool(
        name="project_brain_queue_dispatch_next",
        description="Asynchronously start one fixed Core worker if lock and recovery preflight permit.",
        annotations=DISPATCH_WRITE,
        structured_output=True,
    )
    def project_brain_queue_dispatch_next(reason: ReasonText | None = None) -> dict[str, Any]:
        return service.queue_dispatch_next(reason=reason)

    @mcp.tool(
        name="project_brain_tasks_list",
        description="List bounded task summaries with status, canonical head, and next action.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def project_brain_tasks_list(
        project_id: StableId | None = None,
        status: TaskStatus | None = None,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        return service.tasks_list(
            project_id=project_id,
            status=status.value if status else None,
            limit=limit,
        )

    @mcp.tool(
        name="project_brain_tasks_get",
        description="Inspect one bounded task detail view with current evidence and recent events.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def project_brain_tasks_get(
        task_id: StableId,
        recent_event_limit: Limit = 20,
    ) -> dict[str, Any]:
        return service.tasks_get(task_id=task_id, recent_event_limit=recent_event_limit)

    @mcp.tool(
        name="project_brain_tasks_review",
        description="Atomically review the exact canonical task head without dispatching or merging.",
        annotations=REVIEW_WRITE,
        structured_output=True,
    )
    def project_brain_tasks_review(
        task_id: StableId,
        head_sha: ShaText,
        verdict: Literal["approved", "needs_changes"],
        findings: Annotated[list[ReviewFindingInput], Field(max_length=50)],
    ) -> dict[str, Any]:
        return service.tasks_review(
            {
                "task_id": task_id,
                "head_sha": head_sha,
                "verdict": verdict,
                "findings": [item.model_dump(exclude_none=True) for item in findings],
            }
        )

    @mcp.tool(
        name="project_brain_tasks_recovery_preview",
        description="Preview Core recovery and agent identity without changing state or processes.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def project_brain_tasks_recovery_preview(task_id: StableId) -> dict[str, Any]:
        return service.tasks_recovery_preview(task_id=task_id)

    @mcp.tool(
        name="project_brain_acceptance_probe",
        description=(
            "Consume one Project Brain MCP transport challenge. This records only "
            "unattributed local-or-tunneled transport evidence; it cannot authenticate "
            "ChatGPT or complete external acceptance, and performs no task, file, Git, "
            "or command action."
        ),
        annotations=ACCEPTANCE_PROBE_WRITE,
        structured_output=True,
    )
    def project_brain_acceptance_probe(
        challenge: AcceptanceChallenge,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            run = acceptance._complete_from_mcp_ingress(challenge)
            return {
                "status": "ok",
                "code": "ok",
                "result": {
                    "probe": "mcp_transport_probe_passed",
                    "external_chatgpt_verified": False,
                    "source_attribution": "unavailable",
                    "project_brain_version": __version__,
                    "verified_at": run["verified_at"],
                    "acceptance_run_id": run["run_id"],
                },
            }

        return _guard(operation)  # type: ignore[return-value]

    # The verified and exactly pinned mcp==1.28.1 release builds function
    # argument models with Pydantic's extra="ignore" default. Its public tool
    # API has no hook for changing that generated model, so this deliberately
    # uses private metadata to keep the advertised schema and runtime strict.
    # Any SDK upgrade must first pass server startup, discovery,
    # additionalProperties=false, and unknown-argument compatibility tests.
    for tool in mcp._tool_manager.list_tools():  # type: ignore[attr-defined]
        argument_model = tool.fn_metadata.arg_model
        argument_model.model_config = {**argument_model.model_config, "extra": "forbid"}
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)
