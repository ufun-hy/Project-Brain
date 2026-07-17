"""Independent acceptance and project verification evidence collection."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .models import utc_now
from .runtime import RuntimePaths
from .security import redact_text
from .store import TaskStore
from .acceptance_tasks import ACCEPTANCE_DOCUMENT_PATH, ACCEPTANCE_SOURCE_TYPE
from .commands import git


class VerificationRunner:
    def __init__(self, store: TaskStore, runtime: RuntimePaths) -> None:
        self.store = store
        self.runtime = runtime

    def run(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: str | Path,
        verification_set: dict[str, Any],
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        trusted: dict[str, dict[str, Any]] = {}
        for index, check in enumerate(project.get("verification_commands") or [], start=1):
            if isinstance(check, list):
                trusted[f"project-check-{index}"] = {
                    "id": f"project-check-{index}",
                    "text": f"Project check {index}",
                    "command": check,
                    "always_run": True,
                }
            elif isinstance(check, dict):
                check_id = str(check.get("id") or f"project-check-{index}")
                trusted[check_id] = {
                    "id": check_id,
                    "text": str(check.get("text") or check.get("name") or check_id),
                    "command": check.get("command") or check.get("argv"),
                    "always_run": bool(check.get("always_run", True)),
                }
        referenced: set[str] = set()
        for index, criterion in enumerate(task.get("acceptance_criteria") or [], start=1):
            if isinstance(criterion, str):
                specs.append(
                    {
                        "criterion_id": f"criterion-{index}",
                        "criterion_text": criterion,
                        "command": None,
                        "evidence_type": "manual_required",
                    }
                )
            elif isinstance(criterion, dict):
                verification_id = criterion.get("verification_id")
                command = None
                evidence_type = "manual_required"
                if verification_id:
                    trusted_check = trusted.get(str(verification_id))
                    if trusted_check is not None:
                        command = trusted_check["command"]
                        evidence_type = "trusted_project_command"
                        referenced.add(str(verification_id))
                specs.append(
                    {
                        "criterion_id": str(criterion.get("id") or f"criterion-{index}"),
                        "criterion_text": str(
                            criterion.get("text") or criterion.get("criterion") or f"Criterion {index}"
                        ),
                        "verification_id": verification_id,
                        "command": command,
                        "evidence_type": evidence_type,
                    }
                )
            else:
                specs.append(
                    {
                        "criterion_id": f"criterion-{index}",
                        "criterion_text": f"Invalid criterion value at index {index}",
                        "command": None,
                        "evidence_type": "manual_required",
                    }
                )
        for check_id, check in trusted.items():
            if check_id in referenced or not check["always_run"]:
                continue
            specs.append(
                {
                    "criterion_id": check_id,
                    "criterion_text": check["text"],
                    "verification_id": check_id,
                    "command": check["command"],
                    "evidence_type": "trusted_project_command",
                }
            )

        results: list[dict[str, Any]] = []
        if task.get("source_type") == ACCEPTANCE_SOURCE_TYPE:
            result = self._verify_acceptance_document(task, Path(worktree).resolve())
            result["verification_set_id"] = verification_set["verification_set_id"]
            self.store.record_verification(
                task["task_id"], verification_set["verification_set_id"], result
            )
            results.append(result)
        for index, spec in enumerate(specs, start=1):
            result = self._run_one(
                task["task_id"],
                spec,
                Path(worktree).resolve(),
                verification_set=verification_set,
                artifact_index=index,
            )
            result["verification_set_id"] = verification_set["verification_set_id"]
            self.store.record_verification(
                task["task_id"], verification_set["verification_set_id"], result
            )
            results.append(result)
        return results

    def _verify_acceptance_document(
        self,
        task: dict[str, Any],
        worktree: Path,
    ) -> dict[str, Any]:
        worktree = worktree.resolve()
        created_at = utc_now()
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        expected_path = payload.get("acceptance_document_path")
        expected_content = payload.get("acceptance_document_content")
        base = task.get("base_sha")
        head = task.get("commit") or task.get("head_sha")
        passed = True
        detail = "Controlled acceptance document and changed-file scope match the bound run."
        if expected_path != ACCEPTANCE_DOCUMENT_PATH or not isinstance(expected_content, str):
            passed = False
            detail = "Acceptance task payload is not the fixed RC1 document contract."
        elif not all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40,64}", value)
            for value in (base, head)
        ):
            passed = False
            detail = "Acceptance task canonical Git bounds are invalid."
        else:
            changed = [
                item
                for item in git(
                    worktree,
                    "diff",
                    "--name-only",
                    "--no-renames",
                    f"{base}..{head}",
                    "--",
                ).stdout.splitlines()
                if item
            ]
            target = worktree / ACCEPTANCE_DOCUMENT_PATH
            if changed != [ACCEPTANCE_DOCUMENT_PATH]:
                passed = False
                detail = "Acceptance task changed files outside the one allowed document."
            elif target.is_symlink() or not target.is_file():
                passed = False
                detail = "Controlled acceptance document is missing or is a symbolic link."
            elif worktree not in target.resolve().parents:
                passed = False
                detail = "Controlled acceptance document escapes the task worktree."
            elif target.read_text(encoding="utf-8") != expected_content:
                passed = False
                detail = "Controlled acceptance document content does not match the bound run."
        return {
            "criterion_id": "rc1-acceptance-document",
            "criterion_text": (
                "Only docs/project-brain-acceptance.md changes and exactly records "
                "the bound external acceptance run"
            ),
            "status": "passed" if passed else "failed",
            "evidence_type": "project_brain_fixed_acceptance_check",
            "evidence_summary": detail,
            "command": None,
            "exit_code": None,
            "artifact_path": None,
            "created_at": created_at,
        }

    def _run_one(
        self,
        task_id: str,
        spec: dict[str, Any],
        worktree: Path,
        *,
        verification_set: dict[str, Any],
        artifact_index: int,
    ) -> dict[str, Any]:
        command = spec.get("command")
        created_at = utc_now()
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item for item in command
        ):
            return {
                **spec,
                "status": "not_verified",
                "evidence_summary": "No criterion-specific executable evidence was provided.",
                "command": None,
                "exit_code": None,
                "artifact_path": None,
                "created_at": created_at,
            }
        try:
            completed = subprocess.run(
                command,
                cwd=str(worktree),
                text=True,
                capture_output=True,
                timeout=900,
                env={
                    **os.environ,
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_TERMINAL_PROMPT": "0",
                },
            )
            status = "passed" if completed.returncode == 0 else "failed"
            exit_code: int | None = completed.returncode
            output = redact_text((completed.stdout + "\n" + completed.stderr).strip())
        except FileNotFoundError:
            status = "failed"
            exit_code = None
            output = redact_text(f"Command not found: {command[0]}")
        except subprocess.TimeoutExpired:
            status = "failed"
            exit_code = None
            output = "Verification timed out after 900 seconds"
        try:
            artifact_dir = self.runtime.verification_set_dir(
                task_id,
                attempt_number=verification_set["source_attempt_number"],
                verification_set_id=verification_set["verification_set_id"],
                create=True,
            )
        except ValueError as exc:
            from .errors import InvalidPathError

            raise InvalidPathError(str(exc)) from exc
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in spec["criterion_id"]
        )
        artifact = artifact_dir / f"verification-{artifact_index:03d}-{safe_id}.txt"
        descriptor = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(output[-20000:] + ("\n" if output else ""))
        os.chmod(artifact, 0o600)
        summary = (
            f"Command {status}; exit_code={exit_code}; artifact={artifact.name}"
        )
        return {
            **spec,
            "status": status,
            "evidence_summary": summary,
            "command": command,
            "exit_code": exit_code,
            "artifact_path": str(artifact),
            "created_at": created_at,
        }
