#!/usr/bin/env python3
"""Exercise native onboarding through the helper embedded in a final app."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(helper: Path, runtime: Path, arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [str(helper), "--runtime-root", str(runtime), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"embedded helper failed ({completed.returncode}): {completed.stderr}"
        )
    return json.loads(completed.stdout)


def onboarding_arguments(
    contract: dict[str, Any], repository: Path, *, token: str | None = None
) -> list[str]:
    operation = contract["operations"]["native_onboarding"]
    options = operation["options"]
    arguments = [
        *operation["command_path"],
        str(repository),
        options["resolve_existing"],
        options["name"],
        "Project-Brain",
        options["codex_path"],
        "/usr/bin/true",
        options["auto_push_disabled"],
        options["auto_pr_disabled"],
    ]
    if token is None:
        arguments.append(options["plan"])
    else:
        arguments.extend(
            [options["non_interactive"], options["plan_token"], token]
        )
    arguments.append(options["json"])
    return arguments


def verify(app: Path) -> None:
    app = app.resolve(strict=True)
    helper = app / "Contents/Resources/project-brain"
    contract_path = app / "Contents/Resources/project-brain-cli-contract.json"
    assert helper.is_file(), "final app has no embedded Core helper"
    assert contract_path.is_file(), "final app has no embedded CLI contract"
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    reported = json.loads(
        subprocess.run(
            [str(helper), "cli-contract", "--json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert reported["status"] == "ok"
    assert reported["contract"] == contract
    assert reported["document_sha256"] == hashlib.sha256(contract_bytes).hexdigest()
    assert (
        contract["operations"]["native_onboarding"]["options"]["resolve_existing"]
        == "--resolve-existing"
    )

    with tempfile.TemporaryDirectory(prefix="project-brain-final-app-onboarding.") as raw:
        root = Path(raw)
        runtime = root / "runtime"
        remote = root / "Project-Brain.git"
        repository = root / "Project-Brain"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(remote), str(repository)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repository), "config", "user.email", "ci@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "config", "user.name", "Project Brain CI"],
            check=True,
        )
        (repository / "README.md").write_text("# Project Brain\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-m", "initial"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "push", "-u", "origin", "HEAD:main"],
            check=True,
            capture_output=True,
        )

        initialized = run_json(helper, runtime, ["init", "--json"])
        assert initialized["status"] in {"initialized", "ok"}
        add = onboarding_arguments(contract, repository)
        # First registration deliberately removes resolve-existing while keeping
        # every other argv element identical to the App contract.
        resolve_flag = contract["operations"]["native_onboarding"]["options"][
            "resolve_existing"
        ]
        add.remove(resolve_flag)
        project_id_option = contract["operations"]["native_onboarding"]["options"][
            "project_id"
        ]
        add[3:3] = [project_id_option, "project-brain"]
        first_plan = run_json(helper, runtime, add)
        apply = onboarding_arguments(
            contract, repository, token=first_plan["plan"]["plan_token"]
        )
        apply.remove(resolve_flag)
        apply[3:3] = [project_id_option, "project-brain"]
        first_apply = run_json(helper, runtime, apply)
        assert first_apply["action"] == "add"

        database = runtime / "project-brain.db"
        before_sha = sha256(database)
        before_projects = run_json(helper, runtime, ["projects", "list", "--json"])

        existing_plan = run_json(
            helper, runtime, onboarding_arguments(contract, repository)
        )
        assert existing_plan["plan"]["action"] == "use_existing"
        assert existing_plan["plan"]["project_id"] == "project-brain"
        assert sha256(database) == before_sha

        existing_apply = run_json(
            helper,
            runtime,
            onboarding_arguments(
                contract,
                repository,
                token=existing_plan["plan"]["plan_token"],
            ),
        )
        assert existing_apply["action"] == "use_existing"
        assert sha256(database) == before_sha
        after_projects = run_json(helper, runtime, ["projects", "list", "--json"])
        assert after_projects == before_projects

        update_arguments = onboarding_arguments(contract, repository)
        options = contract["operations"]["native_onboarding"]["options"]
        update_arguments[update_arguments.index(options["auto_push_disabled"])] = options[
            "auto_push_enabled"
        ]
        update_plan = run_json(helper, runtime, update_arguments)
        assert update_plan["plan"]["action"] == "update"
        assert update_plan["plan"]["project_id"] == "project-brain"
        assert sha256(database) == before_sha
        assert run_json(helper, runtime, ["projects", "list", "--json"]) == before_projects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    arguments = parser.parse_args()
    verify(arguments.app)
    print("Final app embedded helper onboarding contract verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
