"""Independent acceptance and project verification evidence collection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .models import utc_now
from .runtime import RuntimePaths
from .security import redact_text
from .store import TaskStore


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
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
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
                specs.append(
                    {
                        "criterion_id": str(criterion.get("id") or f"criterion-{index}"),
                        "criterion_text": str(
                            criterion.get("text") or criterion.get("criterion") or f"Criterion {index}"
                        ),
                        "command": criterion.get("command"),
                        "evidence_type": "command" if criterion.get("command") else "manual_required",
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
        for index, check in enumerate(project.get("verification_commands") or [], start=1):
            if isinstance(check, list):
                command = check
                check_id = f"project-check-{index}"
                text = "Project verification: " + " ".join(check)
            elif isinstance(check, dict):
                command = check.get("command") or check.get("argv")
                check_id = str(check.get("id") or f"project-check-{index}")
                text = str(check.get("text") or check.get("name") or f"Project check {index}")
            else:
                command = None
                check_id = f"project-check-{index}"
                text = f"Invalid project verification at index {index}"
            specs.append(
                {
                    "criterion_id": check_id,
                    "criterion_text": text,
                    "command": command,
                    "evidence_type": "project_command" if command else "manual_required",
                }
            )

        results: list[dict[str, Any]] = []
        for spec in specs:
            result = self._run_one(task["task_id"], spec, Path(worktree).resolve())
            self.store.record_verification(task["task_id"], result)
            results.append(result)
        return results

    def _run_one(
        self,
        task_id: str,
        spec: dict[str, Any],
        worktree: Path,
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
        artifact_dir = self.runtime.results_dir / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in spec["criterion_id"]
        )
        artifact = artifact_dir / f"verification-{safe_id}.txt"
        artifact.write_text(output[-20000:] + ("\n" if output else ""), encoding="utf-8")
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
