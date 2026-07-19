"""Human-readable and JSON operations CLI for Project Brain Core."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .application import health_report, status_report, task_view, worker_result_view
from .engine import TaskEngine
from .errors import (
    AlreadyRunningError,
    InvalidTaskError,
    ProjectConflictError,
    ProjectBrainError,
    StateConflictError,
)
from .executables import find_executable
from .locking import RuntimeLock
from .ingress import TaskImporter
from .projects import ProjectRegistry
from .recovery import RecoveryManager
from .forensics import TerminalWorktreeReconciler
from .runtime import RuntimePaths
from .services import ServiceManager, installed_helper_path
from .security import redact_text
from .store import TaskStore
from .worktrees import WorktreeManager
from .configuration import ConfigurationManager, project_checks, safe_project
from .project_config import (
    EXECUTION_FIELDS,
    LEGACY_CONFIG_REQUIRES_UPDATE,
    config_sha256,
    normalize_execution_profile,
    normalize_legacy_execution_profile,
)
from .project_plans import bind_project_plan, require_matching_project_plan
from .acceptance import ExternalAcceptanceManager
from .acceptance_tasks import acceptance_task_plan, create_acceptance_task
from .cli_contract import cli_contract_sha256, load_cli_contract
from .local_tasks import LocalTaskManager


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="json_output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project-brain")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--runtime-root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the private Core runtime")
    _add_json(init)

    status = sub.add_parser("status", help="Show task status summary")
    _add_json(status)

    cli_contract = sub.add_parser(
        "cli-contract", help="Show the versioned App/Core CLI contract"
    )
    _add_json(cli_contract)

    projects = sub.add_parser("projects", help="Inspect registered projects")
    project_sub = projects.add_subparsers(dest="projects_command", required=True)
    project_list = project_sub.add_parser("list")
    _add_json(project_list)
    project_show = project_sub.add_parser("show")
    project_show.add_argument("project_id")
    _add_json(project_show)
    project_check = project_sub.add_parser("check")
    project_check.add_argument("project_id")
    _add_json(project_check)
    project_add = project_sub.add_parser("add")
    project_add.add_argument("repo_path", type=Path)
    project_add.add_argument(
        "--resolve-existing",
        action="store_true",
        help="Resolve an existing repository identity for native onboarding",
    )
    _project_options(project_add, include_identity=True)
    project_use = project_sub.add_parser("use")
    project_use.add_argument("project_id")
    _project_plan_options(project_use)
    project_update = project_sub.add_parser("update")
    project_update.add_argument("project_id")
    project_update.add_argument("--repo-path", type=Path)
    _project_options(project_update, include_identity=False)
    for name in ("pause", "resume", "remove"):
        item = project_sub.add_parser(name)
        item.add_argument("project_id")
        item.add_argument("--execute", action="store_true")
        _add_json(item)

    config = sub.add_parser("config", help="Plan and apply versioned project config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_status = config_sub.add_parser("status")
    _add_json(config_status)
    for name in ("validate", "plan", "apply"):
        item = config_sub.add_parser(name)
        item.add_argument("--file", type=Path)
        if name == "apply":
            item.add_argument("--execute", action="store_true")
        _add_json(item)
    config_export = config_sub.add_parser("export")
    config_export.add_argument("--file", type=Path, required=True)
    config_export.add_argument("--force", action="store_true")
    _add_json(config_export)

    tasks = sub.add_parser("tasks", help="Inspect tasks")
    task_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    task_list = task_sub.add_parser("list")
    task_list.add_argument("--status")
    task_list.add_argument("--project-id")
    task_list.add_argument("--limit", type=int, default=100)
    _add_json(task_list)
    task_show = task_sub.add_parser("show")
    task_show.add_argument("task_id")
    _add_json(task_show)
    task_enqueue = task_sub.add_parser(
        "enqueue", help="Import a canonical task JSON file"
    )
    task_enqueue.add_argument("--file", type=Path, required=True)
    _add_json(task_enqueue)
    local_plan = task_sub.add_parser(
        "local-plan", help="Plan a strict local App task request from stdin"
    )
    _add_json(local_plan)
    local_create = task_sub.add_parser(
        "local-create", help="Create a reviewed local App task request from stdin"
    )
    local_create.add_argument("--plan-token", required=True)
    _add_json(local_create)
    task_review = task_sub.add_parser(
        "review", help="Record commit-bound review findings"
    )
    task_review.add_argument("task_id")
    task_review.add_argument("--file", type=Path, required=True)
    _add_json(task_review)
    task_recover = task_sub.add_parser("recover", help="Reconcile an interrupted task")
    task_recover.add_argument("task_id")
    recovery_mode = task_recover.add_mutually_exclusive_group()
    recovery_mode.add_argument("--dry-run", action="store_true", default=True)
    recovery_mode.add_argument("--execute", action="store_true")
    recovery_action = task_recover.add_mutually_exclusive_group()
    recovery_action.add_argument(
        "--terminate-agent",
        action="store_true",
        help="With --execute, terminate the persisted Codex process group before recovery",
    )
    recovery_action.add_argument(
        "--confirm-no-agent",
        action="store_true",
        help="Resolve a recovery block after confirming that no matching agent is running",
    )
    recovery_action.add_argument(
        "--resume",
        action="store_true",
        help="Resume a recovery-blocked task after operator inspection",
    )
    recovery_action.add_argument(
        "--cancel",
        action="store_true",
        help="Cancel a recovery-blocked task as a terminal failure",
    )
    _add_json(task_recover)

    acceptance = sub.add_parser(
        "acceptance",
        help="Manage Product Shell external acceptance without a pass override",
    )
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_command", required=True)
    acceptance_status = acceptance_sub.add_parser("status")
    _add_json(acceptance_status)
    acceptance_create = acceptance_sub.add_parser("create")
    acceptance_create.add_argument("--app-version", required=True)
    acceptance_create.add_argument("--tunnel-fingerprint", required=True)
    _add_json(acceptance_create)
    acceptance_waiting = acceptance_sub.add_parser("waiting")
    acceptance_waiting.add_argument("run_id")
    _add_json(acceptance_waiting)
    acceptance_reset = acceptance_sub.add_parser("reset")
    acceptance_reset.add_argument("run_id")
    _add_json(acceptance_reset)
    acceptance_task_plan_parser = acceptance_sub.add_parser("task-plan")
    acceptance_task_plan_parser.add_argument("project_id")
    _add_json(acceptance_task_plan_parser)
    acceptance_task_create = acceptance_sub.add_parser("task-create")
    acceptance_task_create.add_argument("project_id")
    acceptance_task_create.add_argument("--plan-token", required=True)
    _add_json(acceptance_task_create)

    health = sub.add_parser("health", help="Check runtime and project prerequisites")
    _add_json(health)

    readiness = sub.add_parser(
        "readiness", help="Check complete Product Shell local readiness"
    )
    _add_json(readiness)

    cleanup = sub.add_parser("cleanup", help="Preview or clean safe terminal worktrees")
    group = cleanup.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--execute", action="store_true")
    _add_json(cleanup)

    apply = sub.add_parser("apply", help="Claim and execute at most one task")
    apply.add_argument("--max-transient-attempts", type=int, default=3)
    _add_json(apply)

    serve = sub.add_parser("serve", help="Run the loopback-only MCP adapter")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7677)

    service = sub.add_parser(
        "service", help="Manage fixed Product Brain launchd services"
    )
    service_sub = service.add_subparsers(dest="service_command", required=True)
    for name in ("plan", "install", "start", "stop", "restart", "status", "uninstall"):
        item = service_sub.add_parser(name)
        item.add_argument("--helper-path", type=Path)
        _add_json(item)

    return parser


def _project_options(
    parser: argparse.ArgumentParser, *, include_identity: bool
) -> None:
    if include_identity:
        parser.add_argument("--project-id")
    parser.add_argument("--name")
    parser.add_argument("--default-branch")
    parser.add_argument("--codex-path")
    parser.add_argument("--verification-file", type=Path)
    parser.add_argument(
        "--auto-push", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument(
        "--auto-pr", action=argparse.BooleanOptionalAction, default=None
    )
    _project_plan_options(parser)


def _project_plan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plan",
        action="store_true",
        dest="plan_only",
        help="Return the validated mutation plan without writing",
    )
    parser.add_argument(
        "--plan-token",
        help="Bind a non-interactive apply to the exact preceding plan",
    )
    parser.add_argument("--non-interactive", action="store_true")
    _add_json(parser)


def _verification_file(path: Path | None) -> list[Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectBrainError(f"Invalid verification file: {exc}") from exc
    if not isinstance(value, list):
        raise ProjectBrainError("Verification file must contain an array")
    return value


def _derived_project_id(repo: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", repo.name).strip("-.")[:128]
    return value or "project"


def _prepare_project_add(
    args: argparse.Namespace,
    store: TaskStore,
    runtime: RuntimePaths,
    *,
    project_id_override: str | None = None,
    name_override: str | None = None,
) -> dict[str, Any]:
    repo = args.repo_path.expanduser().resolve()
    project_id = project_id_override or args.project_id or _derived_project_id(repo)
    values: dict[str, Any] = {
        "project_id": project_id,
        "name": name_override
        or args.name
        or args.project_id
        or _derived_project_id(repo),
        "repo_path": str(repo),
        "default_branch": args.default_branch,
        "codex_path": args.codex_path,
    }
    if args.auto_push is not None:
        values["auto_push"] = args.auto_push
    if args.auto_pr is not None:
        values["auto_pr"] = args.auto_pr
    verification = _verification_file(args.verification_file)
    if verification is not None:
        values["verification_commands"] = verification
    return ProjectRegistry(store, runtime).prepare(values)


def _add_project_plan(prepared: dict[str, Any]) -> dict[str, Any]:
    digest = config_sha256(normalize_execution_profile(prepared))
    return bind_project_plan(
        {
            "project_id": prepared["project_id"],
            "action": "add",
            "current_revision": None,
            "next_revision": 1,
            "current_sha256": None,
            "next_sha256": digest,
            "current_name": None,
            "next_name": prepared["name"],
            "changed_fields": ["name", *EXECUTION_FIELDS],
            "nonterminal_task_count": 0,
            "task_snapshot_effect": "new tasks bind revision 1",
        }
    )


def _use_existing_project_plan(
    store: TaskStore, current: dict[str, Any]
) -> dict[str, Any]:
    return bind_project_plan(
        {
            "project_id": current["project_id"],
            "action": "use_existing",
            "current_revision": current["config_revision"],
            "next_revision": current["config_revision"],
            "current_sha256": current["config_sha256"],
            "next_sha256": current["config_sha256"],
            "current_name": current["name"],
            "next_name": current["name"],
            "changed_fields": [],
            "nonterminal_task_count": store.nonterminal_task_count(
                current["project_id"]
            ),
            "task_snapshot_effect": "existing and new tasks keep the active revision",
        }
    )


def _resolve_onboarding_add(
    args: argparse.Namespace,
    store: TaskStore,
    runtime: RuntimePaths,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    requested = _prepare_project_add(args, store, runtime)
    existing = ProjectRegistry(store, runtime).resolve_onboarding_identity(requested)
    if existing is None:
        return requested, _add_project_plan(requested), None
    values = {
        **existing,
        "repo_path": requested["repo_path"],
        "remote_url": requested["remote_url"],
    }
    if args.default_branch is not None:
        values["default_branch"] = args.default_branch
    if args.codex_path is not None:
        values["codex_path"] = args.codex_path
        values.pop("codex_command", None)
    if args.auto_push is not None:
        values["auto_push"] = args.auto_push
    if args.auto_pr is not None:
        values["auto_pr"] = args.auto_pr
    verification = _verification_file(args.verification_file)
    if verification is not None:
        values["verification_commands"] = verification
    prepared = ProjectRegistry(store, runtime).prepare(values)
    plan = _update_project_plan(store, existing, prepared)
    if plan["action"] == "noop":
        plan = _use_existing_project_plan(store, existing)
    return prepared, plan, existing


def _prepare_project_update(
    args: argparse.Namespace,
    current: dict[str, Any],
    store: TaskStore,
    runtime: RuntimePaths,
) -> dict[str, Any]:
    values = {**current}
    for key in ("name", "default_branch"):
        if getattr(args, key) is not None:
            values[key] = getattr(args, key)
    if args.repo_path is not None:
        updated_repo = args.repo_path.expanduser().resolve()
        values["repo_path"] = str(updated_repo)
        values["remote_url"] = ProjectRegistry._remote_url(updated_repo)
        if args.default_branch is None:
            values["default_branch"] = ProjectRegistry._default_branch(updated_repo)
    if args.codex_path is not None:
        values["codex_command"] = [
            args.codex_path,
            "exec",
            "--sandbox",
            "workspace-write",
            "-",
        ]
    if args.auto_push is not None:
        values["auto_push"] = args.auto_push
    if args.auto_pr is not None:
        values["auto_pr"] = args.auto_pr
    verification = _verification_file(args.verification_file)
    if verification is not None:
        values["verification_commands"] = verification
    return ProjectRegistry(store, runtime).prepare(values)


def _update_project_plan(
    store: TaskStore,
    current: dict[str, Any],
    prepared: dict[str, Any],
) -> dict[str, Any]:
    prepared_profile = normalize_execution_profile(prepared)
    digest = config_sha256(prepared_profile)
    current_profile = (
        normalize_legacy_execution_profile(current)
        if current.get("config_source") == LEGACY_CONFIG_REQUIRES_UPDATE
        else normalize_execution_profile(current)
    )
    changed = [
        field
        for field in EXECUTION_FIELDS
        if prepared_profile[field] != current_profile[field]
    ]
    if prepared["name"] != current["name"]:
        changed.append("name")
    execution_changed = digest != current["config_sha256"]
    action = "update" if execution_changed else ("rename" if changed else "noop")
    return bind_project_plan(
        {
            "project_id": current["project_id"],
            "action": action,
            "current_revision": current["config_revision"],
            "next_revision": current["config_revision"]
            + (1 if execution_changed else 0),
            "current_sha256": current["config_sha256"],
            "next_sha256": digest,
            "current_name": current["name"],
            "next_name": prepared["name"],
            "changed_fields": changed,
            "nonterminal_task_count": store.nonterminal_task_count(
                current["project_id"]
            ),
            "task_snapshot_effect": (
                "existing tasks keep their snapshot; new tasks bind next revision"
            ),
        }
    )


def _confirm(plan: dict[str, Any], *, non_interactive: bool, json_output: bool) -> bool:
    if non_interactive:
        return True
    if json_output:
        indent = None if os.environ.get("PROJECT_BRAIN_JSON_LINES") == "1" else 2
        print(
            json.dumps(_safe_output(plan), ensure_ascii=False, indent=indent),
            file=sys.stderr,
        )
        print(
            "Apply this project configuration? [y/N] ",
            end="",
            flush=True,
            file=sys.stderr,
        )
        answer = input()
    else:
        _render(plan, json_output=False)
        answer = input("Apply this project configuration? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _human_status(value: dict[str, Any]) -> str:
    lines = ["Project Brain status"]
    counts = value.get("counts", {})
    lines.append(
        "Tasks: "
        + (", ".join(f"{key}={count}" for key, count in counts.items()) or "none")
    )
    for task in value.get("tasks", []):
        lines.extend(
            [
                f"- {task['task_id']} [{task['status']}] project={task['project']}",
                f"  branch={task.get('branch') or '-'} commit={task.get('commit') or '-'} pr={task.get('pr_url') or '-'}",
                f"  elapsed={task.get('elapsed_seconds')}s error={task.get('last_error') or '-'}",
                f"  next={task['next_action']}",
            ]
        )
    return "\n".join(lines)


def _render(value: Any, *, json_output: bool, human: str | None = None) -> None:
    value = _safe_output(value)
    if json_output:
        indent = None if os.environ.get("PROJECT_BRAIN_JSON_LINES") == "1" else 2
        print(json.dumps(value, ensure_ascii=False, indent=indent))
    elif human is not None:
        print(_redact_local_paths(human))
    elif isinstance(value, list):
        for item in value:
            print(" ".join(f"{key}={val}" for key, val in item.items()))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def _read_stdin_json(*, maximum_bytes: int = 64 * 1024) -> Any:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    data = stream.read(maximum_bytes + 1)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data:
        raise InvalidTaskError("Local task request stdin is empty")
    if len(data) > maximum_bytes:
        raise InvalidTaskError("Local task request exceeds the 64 KiB transport limit")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidTaskError(
            "Local task request stdin must be one UTF-8 JSON document"
        ) from exc


def _render_local_task(value: Any) -> None:
    """Keep reviewed local paths while emitting exactly one stdout JSON document."""
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _safe_output(value: Any) -> Any:
    hidden = {
        "argv",
        "command",
        "command_json",
        "codex_command",
        "execution_profile",
        "execution_profile_json",
        "repo_path",
        "worktree_root",
        "allowed_commands",
        "verification_commands",
        "runtime",
        "source",
        "path",
        "artifact_path",
        "worktree_path",
        "config_file",
    }
    if isinstance(value, dict):
        return {
            key: _safe_output(item) for key, item in value.items() if key not in hidden
        }
    if isinstance(value, list):
        return [_safe_output(item) for item in value]
    if isinstance(value, str):
        return _redact_local_paths(value)
    return value


def _redact_local_paths(value: str) -> str:
    return re.sub(
        r"(?:/Users|/private|/tmp|/var|/home)/[^\s,;:)\]]+",
        "<local-path>",
        value,
    )


def _error_payload(exc: ProjectBrainError) -> dict[str, Any]:
    message = _redact_local_paths(redact_text(str(exc)))
    value: dict[str, Any] = {
        "status": "error",
        "error_category": exc.category,
        "error": message,
    }
    if isinstance(exc, ProjectConflictError):
        value["conflict"] = exc.conflict
    return _safe_output(value)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "cli-contract":
        contract = load_cli_contract()
        if args.json_output:
            print(
                json.dumps(
                    {
                        "contract": contract,
                        "document_sha256": cli_contract_sha256(),
                        "status": "ok",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(
                "Project Brain CLI contract "
                f"{contract['contract_version']} (schema {contract['schema_version']})"
            )
        return 0
    runtime_value = RuntimePaths.from_value(args.runtime_root)
    if args.command == "service":
        try:
            manager = ServiceManager(
                runtime_value,
                helper_path=args.helper_path or installed_helper_path(),
            )
            value = getattr(manager, args.service_command)()
            _render(value, json_output=args.json_output)
            return 0
        except ProjectBrainError as exc:
            value = _error_payload(exc)
            print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
            return 2
    runtime_preexisting = runtime_value.database.exists()
    runtime = runtime_value.ensure()
    store = TaskStore(runtime.database)
    try:
        store.initialize()
    except ProjectBrainError as exc:
        value = _error_payload(exc)
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        if os.environ.get("PROJECT_BRAIN_WORKER_OUTPUT") != "1":
            raise
        value = {
            "status": "error",
            "code": "internal",
            "error": redact_text(str(exc))[:2000],
        }
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 3
    try:
        if args.command == "init":
            git = find_executable("git")
            codex = find_executable("codex")
            gh = find_executable("gh")
            gh_authenticated = False
            if gh is not None:
                try:
                    gh_authenticated = (
                        subprocess.run(
                            [gh, "auth", "status"],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=5,
                        ).returncode
                        == 0
                    )
                except (OSError, subprocess.TimeoutExpired):
                    gh_authenticated = False
            checks = {
                "git": git is not None,
                "codex": codex is not None,
                "gh": gh is not None,
                "gh_authenticated": gh_authenticated,
            }
            value = {
                "status": (
                    "already_initialized" if runtime_preexisting else "initialized"
                ),
                "schema_version": store.schema_version(),
                "runtime": str(runtime.root),
                "checks": checks,
            }
            _render(value, json_output=args.json_output)
        elif args.command == "status":
            value = status_report(store)
            _render(value, json_output=args.json_output, human=_human_status(value))
        elif args.command == "projects" and args.projects_command == "list":
            projects = [safe_project(item) for item in store.list_projects()]
            _render(projects, json_output=args.json_output)
        elif args.command == "projects" and args.projects_command == "show":
            _render(
                safe_project(store.get_project(args.project_id)),
                json_output=args.json_output,
            )
        elif args.command == "projects" and args.projects_command == "check":
            value = project_checks(store.get_project(args.project_id), runtime)
            _render(value, json_output=args.json_output)
            return 0 if value["status"] == "healthy" else 1
        elif args.command == "projects" and args.projects_command in {
            "pause",
            "resume",
            "remove",
        }:
            project = store.get_project(args.project_id)
            plan = {
                "status": "planned",
                "project_id": args.project_id,
                "action": args.projects_command,
                "current_accepting_tasks": project["accepting_tasks"],
                "next_accepting_tasks": args.projects_command == "resume",
                "runtime_data_preserved": True,
                "nonterminal_task_count": store.nonterminal_task_count(args.project_id),
            }
            if not args.execute:
                _render(plan, json_output=args.json_output)
            else:
                with RuntimeLock(runtime.lock_file):
                    if args.projects_command == "remove":
                        updated = store.remove_project_registration(args.project_id)
                    else:
                        updated = store.set_project_accepting(
                            args.project_id,
                            args.projects_command == "resume",
                        )
                _render(
                    {
                        "status": "applied",
                        "plan": plan,
                        "project": safe_project(updated),
                    },
                    json_output=args.json_output,
                )
        elif args.command == "projects" and args.projects_command == "add":
            if args.resolve_existing:
                prepared, plan, existing = _resolve_onboarding_add(args, store, runtime)
            else:
                project_id = args.project_id or _derived_project_id(
                    args.repo_path.expanduser().resolve()
                )
                try:
                    store.get_project(project_id)
                except InvalidTaskError:
                    pass
                else:
                    if args.plan_token:
                        raise StateConflictError(
                            "Project was registered after planning; refresh the add plan"
                        )
                    raise ProjectBrainError(
                        f"Project is already registered; use projects update: {project_id}"
                    )
                prepared = _prepare_project_add(args, store, runtime)
                plan = _add_project_plan(prepared)
                existing = None
            if args.plan_only:
                _render(
                    {"status": "planned", "plan": plan}, json_output=args.json_output
                )
            elif not _confirm(
                plan, non_interactive=args.non_interactive, json_output=args.json_output
            ):
                _render(
                    {"status": "cancelled", "plan": plan}, json_output=args.json_output
                )
            else:
                confirmed_token = args.plan_token or (
                    plan["plan_token"] if not args.non_interactive else None
                )
                with RuntimeLock(runtime.lock_file):
                    if args.resolve_existing:
                        locked_prepared, locked_plan, locked_existing = (
                            _resolve_onboarding_add(args, store, runtime)
                        )
                    else:
                        locked_prepared = _prepare_project_add(args, store, runtime)
                        locked_plan = _add_project_plan(locked_prepared)
                        locked_existing = None
                    require_matching_project_plan(locked_plan, confirmed_token)
                    if locked_plan["action"] == "use_existing":
                        assert locked_existing is not None
                        result = {"action": "use_existing", "project": locked_existing}
                    else:
                        result = store.apply_projects(
                            [locked_prepared],
                            source=(
                                "project_onboarding_update"
                                if locked_existing is not None
                                else "projects_add"
                            ),
                            expected_plans={locked_prepared["project_id"]: locked_plan},
                        )[0]
                _render(
                    {
                        "status": "applied",
                        "action": result["action"],
                        "plan": locked_plan,
                        "project": safe_project(result["project"]),
                    },
                    json_output=args.json_output,
                )
        elif args.command == "projects" and args.projects_command == "use":
            current = store.get_project(args.project_id)
            plan = _use_existing_project_plan(store, current)
            if args.plan_only:
                _render(
                    {"status": "planned", "plan": plan}, json_output=args.json_output
                )
            elif not _confirm(
                plan, non_interactive=args.non_interactive, json_output=args.json_output
            ):
                _render(
                    {"status": "cancelled", "plan": plan}, json_output=args.json_output
                )
            else:
                confirmed_token = args.plan_token or (
                    plan["plan_token"] if not args.non_interactive else None
                )
                with RuntimeLock(runtime.lock_file):
                    locked_current = store.get_project(args.project_id)
                    locked_plan = _use_existing_project_plan(store, locked_current)
                    require_matching_project_plan(locked_plan, confirmed_token)
                _render(
                    {
                        "status": "applied",
                        "action": "use_existing",
                        "plan": locked_plan,
                        "project": safe_project(locked_current),
                    },
                    json_output=args.json_output,
                )
        elif args.command == "projects" and args.projects_command == "update":
            current = store.get_project(args.project_id)
            prepared = _prepare_project_update(args, current, store, runtime)
            plan = _update_project_plan(store, current, prepared)
            if args.plan_only:
                _render(
                    {"status": "planned", "plan": plan}, json_output=args.json_output
                )
            elif not _confirm(
                plan, non_interactive=args.non_interactive, json_output=args.json_output
            ):
                _render(
                    {"status": "cancelled", "plan": plan}, json_output=args.json_output
                )
            else:
                confirmed_token = args.plan_token or (
                    plan["plan_token"] if not args.non_interactive else None
                )
                with RuntimeLock(runtime.lock_file):
                    latest = store.get_project(args.project_id)
                    locked_prepared = _prepare_project_update(
                        args, latest, store, runtime
                    )
                    locked_plan = _update_project_plan(store, latest, locked_prepared)
                    require_matching_project_plan(locked_plan, confirmed_token)
                    result = store.apply_projects(
                        [locked_prepared],
                        source="projects_update",
                        expected_plans={args.project_id: locked_plan},
                    )[0]
                _render(
                    {
                        "status": "applied",
                        "plan": locked_plan,
                        "project": safe_project(result["project"]),
                    },
                    json_output=args.json_output,
                )
        elif args.command == "config":
            manager = ConfigurationManager(store, runtime)
            if args.config_command == "status":
                value = manager.status()
            elif args.config_command == "validate":
                value = manager.validate(args.file)
            elif args.config_command == "plan":
                value = manager.plan(args.file)
            elif args.config_command == "apply":
                if args.execute:
                    with RuntimeLock(runtime.lock_file):
                        value = manager.apply(args.file, execute=True)
                else:
                    value = manager.apply(args.file, execute=False)
            elif args.config_command == "export":
                with RuntimeLock(runtime.lock_file):
                    value = manager.export(args.file, force=args.force)
            _render(value, json_output=args.json_output)
        elif args.command == "tasks" and args.tasks_command == "list":
            projects = {item["project_id"]: item for item in store.list_projects()}
            tasks = [
                task_view(task, projects)
                for task in store.list_tasks(
                    status=args.status,
                    project_id=args.project_id,
                    limit=args.limit,
                )
            ]
            _render(tasks, json_output=args.json_output)
        elif args.command == "tasks" and args.tasks_command == "show":
            projects = {item["project_id"]: item for item in store.list_projects()}
            task = task_view(store.get_task(args.task_id), projects)
            task["attempts"] = store.list_attempts(args.task_id)
            task["verification"] = store.list_verifications(args.task_id)
            task["verification_set"] = (
                store.get_verification_set(int(task["verification_set_id"]))
                if task.get("verification_set_id")
                else None
            )
            task["reviews"] = store.list_reviews(args.task_id)
            task["forensic_archive"] = store.get_forensic_archive(args.task_id)
            task["events"] = store.list_events(args.task_id)
            _render(task, json_output=args.json_output)
        elif args.command == "tasks" and args.tasks_command == "enqueue":
            with RuntimeLock(runtime.lock_file):
                task, created = TaskImporter(store).import_file(args.file)
            _render(
                {"status": "created" if created else "duplicate", "task": task},
                json_output=args.json_output,
            )
        elif args.command == "tasks" and args.tasks_command == "local-plan":
            value = LocalTaskManager(store, runtime).plan(_read_stdin_json())
            _render_local_task(value)
        elif args.command == "tasks" and args.tasks_command == "local-create":
            request = _read_stdin_json()
            with RuntimeLock(runtime.lock_file):
                value = LocalTaskManager(store, runtime).create(
                    request, plan_token=args.plan_token
                )
            value["task"] = task_view(
                value["task"],
                {item["project_id"]: item for item in store.list_projects()},
            )
            _render_local_task(value)
        elif args.command == "tasks" and args.tasks_command == "review":
            try:
                review_value = json.loads(
                    args.file.expanduser().resolve().read_text(encoding="utf-8")
                )
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                raise ProjectBrainError(f"Invalid review file: {exc}") from exc
            if not isinstance(review_value, dict):
                raise ProjectBrainError("Review file must contain a JSON object")
            with RuntimeLock(runtime.lock_file):
                applied = store.apply_review_verdict(
                    args.task_id,
                    verdict=review_value.get("verdict"),
                    head_sha=review_value.get("head_sha"),
                    findings=review_value.get("findings", []),
                )
                review = applied["review"]
                task = applied["task"]
            _render(
                {"status": task["status"], "task": task, "review": review},
                json_output=args.json_output,
            )
        elif args.command == "tasks" and args.tasks_command == "recover":
            manager = WorktreeManager(store, runtime)
            with RuntimeLock(runtime.lock_file):
                actions = RecoveryManager(store, manager).reconcile(
                    args.task_id,
                    execute=args.execute,
                    terminate_agent=args.terminate_agent,
                    confirm_no_agent=args.confirm_no_agent,
                    resume=args.resume,
                    cancel=args.cancel,
                )
            _render(
                {"mode": "execute" if args.execute else "dry_run", "actions": actions},
                json_output=args.json_output,
            )
        elif args.command == "acceptance":
            manager = ExternalAcceptanceManager(store)
            if args.acceptance_command == "status":
                value = manager.status()
            elif args.acceptance_command == "create":
                with RuntimeLock(runtime.lock_file):
                    value = manager.create_challenge(
                        app_version=args.app_version,
                        tunnel_fingerprint=args.tunnel_fingerprint,
                    )
            elif args.acceptance_command == "waiting":
                with RuntimeLock(runtime.lock_file):
                    value = {
                        "status": "waiting_for_chatgpt",
                        "run": manager.mark_waiting(args.run_id),
                    }
            elif args.acceptance_command == "reset":
                with RuntimeLock(runtime.lock_file):
                    value = {"status": "failed", "run": manager.reset(args.run_id)}
            elif args.acceptance_command == "task-plan":
                value = acceptance_task_plan(store, args.project_id)
            elif args.acceptance_command == "task-create":
                with RuntimeLock(runtime.lock_file):
                    task, created, plan = create_acceptance_task(
                        store,
                        project_id=args.project_id,
                        plan_token=args.plan_token,
                    )
                value = {
                    "status": "created" if created else "duplicate",
                    "plan": plan,
                    "task": task_view(
                        task,
                        {item["project_id"]: item for item in store.list_projects()},
                    ),
                }
            _render(value, json_output=args.json_output)
        elif args.command == "health":
            value = health_report(store, runtime)
            human = "\n".join(
                [f"Project Brain health: {value['status']}"]
                + [
                    f"- {item['status'].upper()} {item['name']}: {item['detail']}"
                    for item in value["checks"]
                ]
            )
            _render(value, json_output=args.json_output, human=human)
            return 0 if value["status"] == "healthy" else 1
        elif args.command == "readiness":
            from .readiness import product_readiness_report

            value = product_readiness_report(store, runtime)
            _render(value, json_output=args.json_output)
            return 0 if value["status"] == "healthy" else 1
        elif args.command == "cleanup":
            manager = WorktreeManager(store, runtime)
            reconciler = TerminalWorktreeReconciler(store, runtime, manager)
            if not args.execute:
                value = {
                    "mode": "dry_run",
                    "worktrees": reconciler.reconcile(execute=False),
                }
            else:
                with RuntimeLock(runtime.lock_file):
                    value = {
                        "mode": "execute",
                        "worktrees": reconciler.reconcile(execute=True),
                    }
            _render(value, json_output=args.json_output)
        elif args.command == "apply":
            with RuntimeLock(runtime.lock_file):
                value = TaskEngine(
                    store,
                    runtime,
                    max_transient_attempts=args.max_transient_attempts,
                ).apply_once()
            if os.environ.get("PROJECT_BRAIN_WORKER_OUTPUT") == "1":
                value = worker_result_view(value)
            _render(value, json_output=args.json_output)
        elif args.command == "serve":
            from .mcp.server import run_mcp_server

            run_mcp_server(runtime, host=args.host, port=args.port)
        return 0
    except AlreadyRunningError:
        _render(
            {"status": "already_running"},
            json_output=getattr(args, "json_output", False),
        )
        return 0
    except ProjectBrainError as exc:
        value = _error_payload(exc)
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        if os.environ.get("PROJECT_BRAIN_WORKER_OUTPUT") != "1":
            raise
        value = {
            "status": "error",
            "code": "internal",
            "error": redact_text(str(exc))[:2000],
        }
        print(json.dumps(value, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
