from __future__ import annotations

import subprocess
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable

from .gitops import collect_changes, create_worktree, current_head
from .models import CheckResult, resolve_ponytail_mode
from .runtime import RuntimePaths
from .store import Store

POLICY = """
You are executing an already-decided engineering task inside a Project Brain managed Git worktree.

Rules:
- Implement only the supplied task. Do not redesign product requirements.
- Preserve unrelated user work.
- Do not commit.
- Do not push.
- Do not create or update pull requests.
- Do not merge or deploy.
- Do not switch, reset, clean, or modify the user's main checkout.
- Run only implementation-local checks you need while working; Project Brain will run the registered final checks after you finish.

Final response must state: what changed, files touched, checks you personally ran, and any blocker or remaining risk.
""".strip()


def _run_process(
    argv: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    ponytail_mode: str | None = None,
    timeout: int = 1800,
    on_spawn: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    guardian_argv = [
        sys.executable,
        "-m",
        "project_brain_simplified.process_guardian",
        "--parent-pid",
        str(os.getpid()),
        "--",
        *argv,
    ]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            item
            for item in (
                str(Path(__file__).resolve().parents[1]),
                os.environ.get("PYTHONPATH", ""),
            )
            if item
        ),
    }
    if ponytail_mode is not None:
        env["PONYTAIL_DEFAULT_MODE"] = ponytail_mode
    process = subprocess.Popen(
        guardian_argv,
        cwd=cwd,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    if on_spawn is not None:
        on_spawn(process.pid)
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # The child owns a new process group. Only terminate that group, never
        # an arbitrary stale PID or the caller's process group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            argv,
            timeout,
            output=stdout if stdout else exc.output,
            stderr=stderr if stderr else exc.stderr,
        )
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _bounded_output(completed: subprocess.CompletedProcess[str], limit: int = 20000) -> str:
    combined = (completed.stdout + "\n" + completed.stderr).strip()
    return combined[-limit:]


def run_checks(worktree: Path, checks: list[list[str]]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for argv in checks:
        try:
            completed = _run_process(argv, cwd=worktree, timeout=1800)
            results.append(
                CheckResult(
                    argv=list(argv),
                    exit_code=completed.returncode,
                    status="passed" if completed.returncode == 0 else "failed",
                    output=_bounded_output(completed, 12000),
                    stdout=completed.stdout[-12000:],
                    stderr=completed.stderr[-12000:],
                )
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            results.append(
                CheckResult(
                    argv=list(argv),
                    exit_code=124,
                    status="failed",
                    output=(stdout + "\n" + stderr + "\nTimed out").strip()[-12000:],
                    stdout=stdout[-12000:],
                    stderr=(stderr + "\nTimed out").strip()[-12000:],
                )
            )
        except OSError as exc:
            message = f"Could not start check: {exc}"
            results.append(
                CheckResult(
                    argv=list(argv),
                    exit_code=127,
                    status="failed",
                    output=message,
                    stderr=message,
                )
            )
        if results[-1].status == "failed":
            break
    return results


def execute_task(store: Store, runtime: RuntimePaths, task_id: str) -> dict[str, Any]:
    task = store.get_task(task_id)
    project = store.get_project(task["project_id"])
    worktree: Path | None = None
    codex_exit: int | None = None
    codex_summary = ""
    check_results: list[CheckResult] = []
    error: str | None = None
    terminal_status = "failed"
    try:
        ponytail_mode = resolve_ponytail_mode(task.get("ponytail_mode"))
        worktree, base_sha, branch = create_worktree(
            runtime,
            project_id=project["project_id"],
            task_id=task_id,
            repo_path=project["repo_path"],
            default_branch=project["default_branch"],
        )
        store.record_execution_identity(
            task_id, base_sha=base_sha, branch=branch, worktree_path=str(worktree)
        )
        original_prompt = (
            f"{POLICY}\n\nTask goal:\n{task['goal']}\n\nImplementation brief:\n{task['prompt']}\n"
        )
        prompt = f"@ponytail {ponytail_mode}\n\n{original_prompt}"
        try:
            completed = _run_process(
                project["codex_command"],
                cwd=worktree,
                input_text=prompt,
                ponytail_mode=ponytail_mode,
                on_spawn=lambda pid: store.record_codex_supervisor_pid(task_id, pid=pid),
            )
            codex_exit = completed.returncode
            codex_summary = _bounded_output(completed)
        except subprocess.TimeoutExpired as exc:
            codex_exit = 124
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            codex_summary = (stdout + "\n" + stderr + "\nCodex timed out").strip()[-20000:]
        if codex_exit != 0:
            error = f"Codex exited with code {codex_exit}"
        elif current_head(worktree) != base_sha:
            error = "Codex created a commit; simplified Project Brain requires local uncommitted changes"
        else:
            check_results = run_checks(worktree, project["checks"])
            failed = [item for item in check_results if item.status == "failed"]
            if failed:
                error = "One or more registered checks failed"
            else:
                terminal_status = "completed"
    except Exception as exc:
        error = str(exc)

    changed_files: list[str] = []
    diff_text = ""
    if worktree is not None and worktree.exists():
        try:
            changed_files, diff_text = collect_changes(worktree, base_sha=store.get_task(task_id).get("base_sha") or "HEAD")
        except Exception as exc:
            if error:
                error += f"; change collection failed: {exc}"
            else:
                error = f"Change collection failed: {exc}"
                terminal_status = "failed"

    return store.finish_task(
        task_id,
        status=terminal_status,
        codex_exit_code=codex_exit,
        codex_summary=codex_summary,
        changed_files=changed_files,
        diff_text=diff_text,
        checks=[item.as_dict() for item in check_results],
        error=error,
    )
