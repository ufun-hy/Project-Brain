#!/usr/bin/env python3
"""Exercise an Analyze task through the helper inside the final mounted DMG."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def run(
    arguments: list[str],
    *,
    environment: dict[str, str],
    stdin: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        input=stdin,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {arguments!r}\n{completed.stderr}"
        )
    return completed


def run_json(
    helper: Path,
    runtime: Path,
    arguments: list[str],
    *,
    environment: dict[str, str],
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completed = run(
        [str(helper), "--runtime-root", str(runtime), *arguments],
        environment=environment,
        stdin=(
            json.dumps(request, ensure_ascii=False, sort_keys=True)
            if request is not None
            else None
        ),
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict), "embedded helper stdout must be one JSON document"
    return value


def git(repository: Path, *arguments: str, environment: dict[str, str]) -> str:
    return run(
        ["/usr/bin/git", "-C", str(repository), *arguments],
        environment=environment,
    ).stdout.strip()


def onboard(
    helper: Path,
    runtime: Path,
    repository: Path,
    analyzer: Path,
    contract: dict[str, Any],
    environment: dict[str, str],
) -> None:
    operation = contract["operations"]["native_onboarding"]
    options = operation["options"]
    fixed = [
        *operation["command_path"],
        str(repository),
        options["project_id"],
        "project-brain",
        options["name"],
        "Project-Brain",
        options["codex_path"],
        str(analyzer),
        options["auto_push_disabled"],
        options["auto_pr_disabled"],
    ]
    planned = run_json(
        helper,
        runtime,
        [*fixed, options["plan"], options["json"]],
        environment=environment,
    )
    applied = run_json(
        helper,
        runtime,
        [
            *fixed,
            options["non_interactive"],
            options["plan_token"],
            planned["plan"]["plan_token"],
            options["json"],
        ],
        environment=environment,
    )
    assert applied["action"] == "add"


def downgrade_fixture_to_v8(runtime: Path) -> None:
    database = runtime / "project-brain.db"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE tasks SET status = 'accepted' WHERE task_id = 'upgrade-sentinel'")
        # Build a truthful pre-RFC-008 schema-v8 fixture. A real v8 database has
        # neither the v9 structures nor a v9 migration-ledger entry; removing
        # only the structures would create an impossible, internally
        # inconsistent database and would correctly prevent migration replay.
        connection.execute("DELETE FROM schema_migrations WHERE version = 9")
        connection.execute("DROP TABLE local_task_plans")
        connection.execute("ALTER TABLE tasks DROP COLUMN result_json")
        connection.execute("ALTER TABLE tasks DROP COLUMN delivery_json")
        connection.execute("ALTER TABLE tasks DROP COLUMN local_task_type")
        connection.execute("PRAGMA user_version = 8")


def verify(dmg: Path) -> None:
    if os.environ.get("CI") != "true":
        raise AssertionError("final DMG local-task verification is restricted to isolated CI")
    dmg = dmg.resolve(strict=True)
    installed_app = Path("/Applications/Project Brain.app")
    if installed_app.exists():
        raise AssertionError("refusing to replace a pre-existing Project Brain.app")

    with tempfile.TemporaryDirectory(prefix="project-brain-final-local-task.") as raw:
        root = Path(raw)
        mount = root / "mount"
        home = root / "home"
        runtime = home / ".project-brain"
        mount.mkdir()
        home.mkdir()
        environment = {
            "HOME": str(home),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
        attached = False
        installed = False
        services_installed = False
        helper: Path | None = None
        try:
            run(
                [
                    "/usr/bin/hdiutil",
                    "attach",
                    "-quiet",
                    "-readonly",
                    "-nobrowse",
                    "-mountpoint",
                    str(mount),
                    str(dmg),
                ],
                environment=environment,
            )
            attached = True
            shutil.copytree(mount / "Project Brain.app", installed_app, copy_function=shutil.copy2)
            installed = True
            helper = installed_app / "Contents/Resources/project-brain"
            contract_path = installed_app / "Contents/Resources/project-brain-cli-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            assert contract["operations"]["local_task"]["transport"] == "stdin_json"

            managed_helper = (
                home
                / "Library/Application Support/Project Brain/bin/project-brain"
            )
            managed_helper.parent.mkdir(parents=True, mode=0o700)
            shutil.copy2(helper, managed_helper)
            managed_helper.chmod(0o755)

            remote = root / "Project-Brain.git"
            repository = root / "Project-Brain"
            run(["/usr/bin/git", "init", "--bare", str(remote)], environment=environment)
            run(["/usr/bin/git", "clone", str(remote), str(repository)], environment=environment)
            git(repository, "config", "user.email", "ci@example.invalid", environment=environment)
            git(repository, "config", "user.name", "Project Brain CI", environment=environment)
            (repository / "README.md").write_text("# Project Brain\n", encoding="utf-8")
            git(repository, "add", "README.md", environment=environment)
            git(repository, "commit", "-m", "initial", environment=environment)
            git(repository, "branch", "-M", "main", environment=environment)
            git(repository, "push", "-u", "origin", "HEAD:main", environment=environment)
            run(
                [
                    "/usr/bin/git",
                    "-C",
                    str(remote),
                    "symbolic-ref",
                    "HEAD",
                    "refs/heads/main",
                ],
                environment=environment,
            )

            analyzer = root / "analyze"
            analyzer.write_text(
                "#!/bin/sh\n/bin/cat >/dev/null\n"
                "/usr/bin/printf '%s\\n' 'Repository readiness analysis completed.'\n",
                encoding="utf-8",
            )
            analyzer.chmod(0o755)

            initialized = run_json(
                helper, runtime, ["init", "--json"], environment=environment
            )
            assert initialized["schema_version"] == 9
            onboard(helper, runtime, repository, analyzer, contract, environment)

            sentinel_file = root / "upgrade-sentinel.json"
            sentinel_file.write_text(
                json.dumps(
                    {
                        "task_id": "upgrade-sentinel",
                        "project_id": "project-brain",
                        "dedupe_key": "upgrade-sentinel",
                        "revision": 1,
                        "source_type": "artifact_upgrade_fixture",
                        "source_message_id": None,
                        "goal": "Preserve this task across schema migration.",
                        "acceptance_criteria": [],
                        "task_type": "codex",
                        "payload": {"prompt": "Preservation fixture."},
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            run_json(
                helper,
                runtime,
                ["tasks", "enqueue", "--file", str(sentinel_file), "--json"],
                environment=environment,
            )
            downgrade_fixture_to_v8(runtime)
            migrated = run_json(
                helper, runtime, ["init", "--json"], environment=environment
            )
            assert migrated["schema_version"] == 9
            sentinel = run_json(
                helper,
                runtime,
                ["tasks", "show", "upgrade-sentinel", "--json"],
                environment=environment,
            )
            assert sentinel["status"] == "accepted"
            assert sentinel.get("local_task_type") is None

            run_json(
                helper,
                runtime,
                [
                    "service",
                    "install",
                    "--helper-path",
                    str(managed_helper),
                    "--json",
                ],
                environment=environment,
            )
            services_installed = True
            deadline = time.monotonic() + 30
            while True:
                service = run_json(
                    helper,
                    runtime,
                    ["service", "status", "--json"],
                    environment=environment,
                )
                worker = next(item for item in service["services"] if item["name"] == "worker")
                if worker["state"] in {"healthy", "running"}:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(f"worker did not become ready: {service}")
                time.sleep(0.25)

            checkout_head = git(repository, "rev-parse", "HEAD", environment=environment)
            checkout_status = git(
                repository,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                environment=environment,
            )
            request = {
                "schema_version": 1,
                "source": "local_app",
                "project_id": "project-brain",
                "task_type": "analysis",
                "goal": "Review repository readiness and return an actionable summary.",
                "acceptance_criteria": ["Do not modify repository files"],
                "delivery": {"commit": False, "push": False, "draft_pr": False},
            }
            planned = run_json(
                helper,
                runtime,
                ["tasks", "local-plan", "--json"],
                environment=environment,
                request=request,
            )
            assert planned["plan"]["readiness"]["ready"] is True
            assert planned["plan"]["external_chatgpt_acceptance"] == "pending"
            created = run_json(
                helper,
                runtime,
                [
                    "tasks",
                    "local-create",
                    "--plan-token",
                    planned["plan"]["plan_token"],
                    "--json",
                ],
                environment=environment,
                request=request,
            )
            task_id = created["task"]["task_id"]

            deadline = time.monotonic() + 60
            task: dict[str, Any] = {}
            while time.monotonic() < deadline:
                run_json(helper, runtime, ["apply", "--json"], environment=environment)
                task = run_json(
                    helper,
                    runtime,
                    ["tasks", "show", task_id, "--json"],
                    environment=environment,
                )
                if task["status"] == "completed":
                    break
                if task["status"] in {"failed", "recovery_blocked"}:
                    raise AssertionError(f"Analyze task failed: {task}")
                time.sleep(0.25)
            assert task["status"] == "completed"
            assert task["local_task_type"] == "analysis"
            assert task["source_type"] == "local_app"
            assert task["result"]["kind"] == "analysis"
            assert "readiness analysis completed" in task["result"]["summary"]
            assert task["commit"] is None and task["pr_url"] is None

            restarted_view = run_json(
                helper,
                runtime,
                ["tasks", "show", task_id, "--json"],
                environment=environment,
            )
            assert restarted_view["result"] == task["result"]
            assert git(repository, "rev-parse", "HEAD", environment=environment) == checkout_head
            assert (
                git(
                    repository,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    environment=environment,
                )
                == checkout_status
            )
            projects = run_json(
                helper,
                runtime,
                ["projects", "list", "--json"],
                environment=environment,
            )
            assert [item["project_id"] for item in projects] == ["project-brain"]
            assert not (home / "Library/Keychains").exists()
        finally:
            if services_installed and helper is not None:
                run_json(
                    helper,
                    runtime,
                    ["service", "uninstall", "--json"],
                    environment=environment,
                )
            if installed:
                shutil.rmtree(installed_app)
            if attached:
                run(
                    ["/usr/bin/hdiutil", "detach", "-quiet", str(mount)],
                    environment=environment,
                    check=False,
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dmg", type=Path)
    arguments = parser.parse_args()
    verify(arguments.dmg)
    print(
        "Final DMG embedded helper Analyze task passed with schema upgrade, "
        "restart persistence, and unchanged main checkout"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
