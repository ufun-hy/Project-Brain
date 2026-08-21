from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mcp_server import run_server
from .models import PONYTAIL_MODES
from .runtime import RuntimePaths
from .service import Service


def _json_argv(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or not all(isinstance(x, str) and x for x in parsed):
        raise argparse.ArgumentTypeError("expected JSON argv array")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(prog="project-brain-simplified")
    parser.add_argument("--runtime-root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")

    projects = sub.add_parser("projects")
    psub = projects.add_subparsers(dest="projects_command", required=True)
    add = psub.add_parser("add")
    add.add_argument("repo_path")
    add.add_argument("--id", required=True)
    add.add_argument("--name")
    add.add_argument("--default-branch", default="main")
    add.add_argument(
        "--codex-command",
        type=_json_argv,
        default=["codex", "exec", "--sandbox", "workspace-write", "-"],
    )
    add.add_argument("--check", type=_json_argv, action="append", default=[])
    psub.add_parser("list")

    context = sub.add_parser("context")
    context.add_argument("project_id")

    tasks = sub.add_parser("tasks")
    tsub = tasks.add_subparsers(dest="tasks_command", required=True)
    run = tsub.add_parser("run")
    run.add_argument("project_id")
    run.add_argument("--goal", required=True)
    group = run.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt")
    group.add_argument("--prompt-file")
    run.add_argument("--ponytail-mode", choices=sorted(PONYTAIL_MODES))
    get = tsub.add_parser("get")
    get.add_argument("task_id")
    lst = tsub.add_parser("list")
    lst.add_argument("--project-id")
    lst.add_argument("--limit", type=int, default=20)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7677)

    args = parser.parse_args()
    runtime = RuntimePaths.from_value(args.runtime_root).ensure()
    if args.command == "serve":
        run_server(runtime.root, host=args.host, port=args.port)
        return 0
    service = Service(runtime)
    if args.command == "init":
        result = service.health()
    elif args.command == "projects" and args.projects_command == "add":
        result = service.register_project(
            project_id=args.id,
            name=args.name or args.id,
            repo_path=args.repo_path,
            default_branch=args.default_branch,
            codex_command=args.codex_command,
            checks=args.check,
        )
    elif args.command == "projects" and args.projects_command == "list":
        result = {"projects": service.projects_list()}
    elif args.command == "context":
        result = service.project_context_get(args.project_id)
    elif args.command == "tasks" and args.tasks_command == "run":
        prompt = args.prompt
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        result = service.task_run(
            project_id=args.project_id,
            goal=args.goal,
            prompt=prompt,
            ponytail_mode=args.ponytail_mode,
        )
    elif args.command == "tasks" and args.tasks_command == "get":
        result = service.tasks_get(args.task_id)
    elif args.command == "tasks" and args.tasks_command == "list":
        result = {"tasks": service.tasks_list(project_id=args.project_id, limit=args.limit)}
    else:
        parser.error("unsupported command")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
