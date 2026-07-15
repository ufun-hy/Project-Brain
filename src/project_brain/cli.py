"""Human-readable and JSON operations CLI for Project Brain Core."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .application import health_report, status_report, task_view, worker_result_view
from .engine import TaskEngine
from .errors import AlreadyRunningError, ProjectBrainError
from .locking import RuntimeLock
from .ingress import TaskImporter
from .projects import ProjectRegistry
from .recovery import RecoveryManager
from .forensics import TerminalWorktreeReconciler
from .runtime import RuntimePaths
from .security import redact_text
from .store import TaskStore
from .worktrees import WorktreeManager


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="json_output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project-brain")
    parser.add_argument("--runtime-root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show task status summary")
    _add_json(status)

    projects = sub.add_parser("projects", help="Inspect registered projects")
    project_sub = projects.add_subparsers(dest="projects_command", required=True)
    project_list = project_sub.add_parser("list")
    _add_json(project_list)

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
    task_enqueue = task_sub.add_parser("enqueue", help="Import a canonical task JSON file")
    task_enqueue.add_argument("--file", type=Path, required=True)
    _add_json(task_enqueue)
    task_review = task_sub.add_parser("review", help="Record commit-bound review findings")
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

    health = sub.add_parser("health", help="Check runtime and project prerequisites")
    _add_json(health)

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

    return parser


def _human_status(value: dict[str, Any]) -> str:
    lines = ["Project Brain status"]
    counts = value.get("counts", {})
    lines.append("Tasks: " + (", ".join(f"{key}={count}" for key, count in counts.items()) or "none"))
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
    if json_output:
        indent = None if os.environ.get("PROJECT_BRAIN_JSON_LINES") == "1" else 2
        print(json.dumps(value, ensure_ascii=False, indent=indent))
    elif human is not None:
        print(human)
    elif isinstance(value, list):
        for item in value:
            print(" ".join(f"{key}={val}" for key, val in item.items()))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = RuntimePaths.from_value(args.runtime_root).ensure()
    store = TaskStore(runtime.database)
    try:
        store.initialize()
    except ProjectBrainError as exc:
        message = redact_text(str(exc)) if os.environ.get("PROJECT_BRAIN_WORKER_OUTPUT") == "1" else str(exc)
        value = {"status": "error", "error_category": exc.category, "error": message}
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
        if args.command == "status":
            value = status_report(store)
            _render(value, json_output=args.json_output, human=_human_status(value))
        elif args.command == "projects" and args.projects_command == "list":
            projects = store.list_projects()
            _render(projects, json_output=args.json_output)
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
        elif args.command == "tasks" and args.tasks_command == "review":
            try:
                review_value = json.loads(args.file.expanduser().resolve().read_text(encoding="utf-8"))
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
            _render({"status": task["status"], "task": task, "review": review}, json_output=args.json_output)
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
        elif args.command == "health":
            value = health_report(store, runtime)
            human = "\n".join(
                [f"Project Brain health: {value['status']}"]
                + [f"- {item['status'].upper()} {item['name']}: {item['detail']}" for item in value["checks"]]
            )
            _render(value, json_output=args.json_output, human=human)
            return 0 if value["status"] == "healthy" else 1
        elif args.command == "cleanup":
            manager = WorktreeManager(store, runtime)
            reconciler = TerminalWorktreeReconciler(store, runtime, manager)
            if not args.execute:
                value = {"mode": "dry_run", "worktrees": reconciler.reconcile(execute=False)}
            else:
                with RuntimeLock(runtime.lock_file):
                    value = {
                        "mode": "execute",
                        "worktrees": reconciler.reconcile(execute=True),
                    }
            _render(value, json_output=args.json_output)
        elif args.command == "apply":
            with RuntimeLock(runtime.lock_file):
                if not store.list_projects() and runtime.config_file.exists():
                    ProjectRegistry(store, runtime).load_config(runtime.config_file)
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
        _render({"status": "already_running"}, json_output=getattr(args, "json_output", False))
        return 0
    except ProjectBrainError as exc:
        message = redact_text(str(exc)) if os.environ.get("PROJECT_BRAIN_WORKER_OUTPUT") == "1" else str(exc)
        value = {"status": "error", "error_category": exc.category, "error": message}
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
