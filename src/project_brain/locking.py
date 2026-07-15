"""Process-wide runtime lock using the macOS/Linux flock contract."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import IO, Any

from .errors import AlreadyRunningError
from .models import utc_now


class RuntimeLock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._handle: IO[str] | None = None

    def acquire(self) -> "RuntimeLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        handle = self.path.open("a+", encoding="utf-8")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise AlreadyRunningError("Another Project Brain process holds the runtime lock") from exc
        self._handle = handle
        self._write({"pid": os.getpid(), "acquired_at": utc_now(), "status": "running"})
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        self._write({"pid": os.getpid(), "released_at": utc_now(), "status": "released"})
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def metadata(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @classmethod
    def is_available(cls, path: str | Path) -> bool:
        lock = cls(path)
        try:
            lock.acquire()
        except AlreadyRunningError:
            return False
        lock.release()
        return True

    @classmethod
    def probe_available(cls, path: str | Path) -> bool:
        """Check flock availability without creating or rewriting lock metadata."""
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return True
        try:
            handle = target.open("r", encoding="utf-8")
        except FileNotFoundError:
            return True
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return True
        finally:
            handle.close()

    def _write(self, value: dict[str, Any]) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        self._handle.truncate()
        json.dump(value, self._handle, ensure_ascii=False)
        self._handle.write("\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def __enter__(self) -> "RuntimeLock":
        return self.acquire()

    def __exit__(self, *_: object) -> None:
        self.release()
