"""Classified errors used by the Core task engine."""

from __future__ import annotations


class ProjectBrainError(RuntimeError):
    """Base error carrying retry and category metadata."""

    category = "project_brain_error"
    retryable = False


class ConfigurationError(ProjectBrainError):
    category = "configuration"


class InvalidTaskError(ProjectBrainError):
    category = "invalid_task"


class InvalidPathError(ProjectBrainError):
    category = "invalid_path"


class WorktreeError(ProjectBrainError):
    category = "worktree"


class FetchError(WorktreeError):
    category = "git_fetch"
    retryable = True


class NoChangesError(ProjectBrainError):
    category = "no_changes"


class TaskHistoryError(ProjectBrainError):
    category = "task_history"


class VerificationFailedError(ProjectBrainError):
    category = "verification_failed"


class TransientTaskError(ProjectBrainError):
    category = "transient"
    retryable = True


class AlreadyRunningError(ProjectBrainError):
    category = "already_running"
    retryable = True


class StateTransitionError(ProjectBrainError):
    category = "state_transition"


class ExternalCommandError(ProjectBrainError):
    category = "external_command"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.returncode = returncode
