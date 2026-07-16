"""One-task-per-process application service for Core execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import run_named_command, write_files
from .codex import CodexAdapter
from .errors import ProjectBrainError, RecoveryError, VerificationFailedError
from .git_history import GitHistoryNormalizer, NormalizedHistory
from .commands import git
from .errors import TaskHistoryError
from .github import GitHubAdapter
from .forensics import TerminalWorktreeReconciler
from .models import AttemptPhase, TaskStatus
from .repository import RepositorySeal
from .recovery import RecoveryManager
from .runtime import RuntimePaths
from .store import TaskStore
from .verification import VerificationRunner
from .worktrees import WorktreeManager


class TaskEngine:
    def __init__(
        self,
        store: TaskStore,
        runtime: RuntimePaths,
        *,
        max_transient_attempts: int = 3,
        worktrees: WorktreeManager | None = None,
        normalizer: GitHistoryNormalizer | None = None,
        codex: CodexAdapter | None = None,
        verification: VerificationRunner | None = None,
        github: GitHubAdapter | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime
        self.max_transient_attempts = max(1, max_transient_attempts)
        self.worktrees = worktrees or WorktreeManager(store, runtime)
        self.normalizer = normalizer or GitHistoryNormalizer()
        self.codex = codex or CodexAdapter(store, self.normalizer)
        self.verification = verification or VerificationRunner(store, runtime)
        self.github = github or GitHubAdapter()

    def apply_once(self) -> dict[str, Any]:
        """Claim and execute no more than one task, then return structured state."""
        # Production entrypoints hold RuntimeLock around this call. Cleanup uses
        # database registration, task state, PID, heartbeat, and path checks.
        recovery = RecoveryManager(self.store, self.worktrees).reconcile_for_claims(
            execute=True
        )
        TerminalWorktreeReconciler(
            self.store, self.runtime, self.worktrees
        ).reconcile(execute=True)
        if not recovery.claim_safe:
            return {
                "status": "blocked",
                "task": None,
                **recovery.as_dict(),
            }
        task = self.store.claim_next()
        if task is None:
            return {
                "status": "idle",
                "task": None,
                **recovery.as_dict(),
            }
        try:
            project = self.store.task_execution_profile(task)
            worktree_record = self.worktrees.create(task, project)
            task = self.store.get_task(task["task_id"])
            worktree = Path(worktree_record["path"])
            self.store.heartbeat_worktree(task["task_id"])
            phase = AttemptPhase(task["attempt_phase"])
            if phase is AttemptPhase.IMPLEMENTATION:
                snapshot = self.normalizer.capture(
                    worktree,
                    expected_branch=worktree_record["branch"],
                    base_sha=worktree_record["base_sha"],
                )
                history = self._execute_action(task, project, worktree, snapshot)
                self.store.heartbeat_worktree(task["task_id"])
                task = self.store.set_task_fields(
                    task["task_id"], head_sha=history.commit, commit=history.commit
                )
                task = self.store.set_attempt_phase(task["task_id"], AttemptPhase.VERIFICATION)
            else:
                history = self._resume_canonical(task, worktree_record, worktree)

            if AttemptPhase(task["attempt_phase"]) is AttemptPhase.VERIFICATION:
                verification_set = self.store.create_verification_set(
                    task["task_id"], canonical_head_sha=history.commit
                )
                task = self.store.get_task(task["task_id"])
                seal = RepositorySeal.capture(
                    worktree,
                    project=project,
                    expected_branch=worktree_record["branch"],
                    expected_head=history.commit,
                )
                try:
                    evidence = self.verification.run(
                        task=task,
                        project=project,
                        worktree=worktree,
                        verification_set=verification_set,
                    )
                    self.store.heartbeat_worktree(task["task_id"])
                    seal.verify(worktree, project=project)
                    failed_evidence = [
                        item for item in evidence if item["status"] == "failed"
                    ]
                    if failed_evidence:
                        names = ", ".join(
                            item["criterion_id"] for item in failed_evidence
                        )
                        raise VerificationFailedError(f"Verification failed: {names}")
                except Exception:
                    self.store.finalize_verification_set(
                        verification_set["verification_set_id"], status="failed"
                    )
                    raise
                self.store.finalize_verification_set(
                    verification_set["verification_set_id"], status="completed"
                )
                task = self.store.set_attempt_phase(task["task_id"], AttemptPhase.PUBLICATION)
            else:
                evidence = self.store.publication_evidence(task["task_id"])

            publication: dict[str, Any] = {"pushed": False, "pr_url": task.get("pr_url")}
            if project.get("auto_push", True):
                publication_seal = RepositorySeal.capture(
                    worktree,
                    project=project,
                    expected_branch=worktree_record["branch"],
                    expected_head=history.commit,
                )
                publication = self.github.publish(
                    task=task, project=project, worktree=worktree
                )
                self.store.heartbeat_worktree(task["task_id"])
                publication_seal.verify(worktree, project=project)
                if publication.get("pr_url"):
                    task = self.store.set_task_fields(
                        task["task_id"], pr_url=publication["pr_url"]
                    )
            self.store.heartbeat_worktree(task["task_id"])
            self.store.set_attempt_phase(task["task_id"], AttemptPhase.REVIEW)
            task = self.store.transition(
                task["task_id"],
                TaskStatus.AWAITING_REVIEW,
                event_type="execution_completed",
                payload={
                    "commit": history.commit,
                    "source_commits": history.source_commits,
                    "changed_files": history.changed_files,
                    "verification_count": len(evidence),
                },
            )
            self.store.finish_attempt(task["task_id"], status="completed")
            release: dict[str, Any] | None = None
            if publication.get("pushed"):
                try:
                    release = self.worktrees.release_review_worktree(task["task_id"])
                    task = self.store.get_task(task["task_id"])
                except Exception as exc:
                    release = {"action": "retained", "reason": str(exc)}
            return {
                "status": task["status"],
                "task": task,
                "evidence": evidence,
                "worktree_release": release,
            }
        except VerificationFailedError as exc:
            task = self.store.transition(
                task["task_id"],
                TaskStatus.VERIFICATION_FAILED,
                event_type="verification_failed",
                payload={"category": exc.category},
                last_error=str(exc),
            )
            self.store.finish_attempt(
                task["task_id"],
                status="verification_failed",
                error_category=exc.category,
                error_message=str(exc),
            )
            return {
                "status": task["status"],
                "task": task,
                "evidence": self.store.list_verifications(
                    task["task_id"],
                    verification_set_id=task["verification_set_id"],
                ),
            }
        except Exception as exc:
            return self._handle_error(task, exc)

    def _execute_action(
        self,
        task: dict[str, Any],
        project: dict[str, Any],
        worktree: Path,
        snapshot: Any,
    ) -> NormalizedHistory:
        if task["task_type"] == "codex":
            return self.codex.execute(
                task=task,
                project=project,
                worktree=worktree,
                snapshot=snapshot,
            )
        if task["task_type"] == "write_files":
            write_files(worktree, task["payload"])
        elif task["task_type"] == "command":
            run_named_command(worktree, task["payload"], project)
        else:
            raise ProjectBrainError(f"Unsupported task type: {task['task_type']}")
        message = task["payload"].get("commit_message") or f"feat: complete {task['task_id']}"
        return self.normalizer.normalize(worktree, snapshot, message=str(message))

    @staticmethod
    def _resume_canonical(
        task: dict[str, Any],
        worktree_record: dict[str, Any],
        worktree: Path,
    ) -> NormalizedHistory:
        branch = git(
            worktree, "symbolic-ref", "--quiet", "--short", "HEAD", check=False
        ).stdout.strip()
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        status = git(worktree, "status", "--porcelain").stdout.strip()
        if branch != worktree_record["branch"] or head != task["commit"] or status:
            raise TaskHistoryError(
                "Cannot resume publication because the recorded canonical worktree changed"
            )
        return NormalizedHistory(
            commit=task["commit"],
            head_before=head,
            source_commits=[],
            changed_files=[],
        )

    def _handle_error(self, task: dict[str, Any], exc: Exception) -> dict[str, Any]:
        category = getattr(exc, "category", "unexpected")
        retryable = bool(getattr(exc, "retryable", False))
        current = self.store.get_task(task["task_id"])
        if isinstance(exc, RecoveryError):
            updated = self.store.block_running_task(
                task["task_id"], reason=str(exc)
            )
            return {"status": updated["status"], "task": updated}
        if retryable and current["attempt_count"] < self.max_transient_attempts:
            target = TaskStatus.RETRY_PENDING
            attempt_status = "retry_pending"
        else:
            target = TaskStatus.FAILED
            attempt_status = "failed"
        if target is TaskStatus.RETRY_PENDING and current["attempt_phase"] not in {
            AttemptPhase.VERIFICATION.value,
            AttemptPhase.PUBLICATION.value,
        }:
            self.store.set_attempt_phase(task["task_id"], AttemptPhase.IMPLEMENTATION)
        updated = self.store.transition(
            task["task_id"],
            target,
            event_type="execution_failed",
            payload={"category": category, "retryable": retryable},
            last_error=str(exc),
        )
        self.store.finish_attempt(
            task["task_id"],
            status=attempt_status,
            error_category=category,
            error_message=str(exc),
        )
        result: dict[str, Any] = {"status": updated["status"], "task": updated}
        return result
