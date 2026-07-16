"""Source-neutral canonical task ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import InvalidTaskError
from .models import CanonicalTask
from .store import TaskStore


class TaskImporter:
    """Validate canonical task envelopes before persistence.

    Source adapters may translate their native messages to this envelope, but
    they cannot provide executable argv. Criteria may only reference trusted
    verification IDs registered in project configuration.
    """

    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def import_file(self, path: str | Path) -> tuple[dict[str, Any], bool]:
        source = Path(path).expanduser().resolve()
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise InvalidTaskError(f"Task import file does not exist: {source}") from exc
        except json.JSONDecodeError as exc:
            raise InvalidTaskError(f"Invalid task JSON in {source}: {exc}") from exc
        return self.import_value(value)

    def import_value(self, value: Any) -> tuple[dict[str, Any], bool]:
        if not isinstance(value, dict):
            raise InvalidTaskError("Canonical task import must be a JSON object")
        allowed = set(CanonicalTask.__dataclass_fields__)
        unknown = set(value).difference(allowed)
        if unknown:
            raise InvalidTaskError(
                f"Unsupported canonical task fields: {', '.join(sorted(unknown))}"
            )
        try:
            task = CanonicalTask(**value)
        except TypeError as exc:
            raise InvalidTaskError(f"Invalid canonical task envelope: {exc}") from exc
        task.validate()
        # Verification IDs and the matching execution profile are validated and
        # bound inside the store's single task-creation transaction.
        return self.store.insert_task(task)
