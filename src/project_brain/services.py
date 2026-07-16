"""Controlled launchd service lifecycle for the macOS Product Shell."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ServiceError
from .executables import LAUNCHD_TOOL_PATH
from .runtime import RuntimePaths


WORKER_LABEL = "com.projectbrain.worker"
MCP_LABEL = "com.projectbrain.mcp"
LAUNCHCTL = "/bin/launchctl"

Runner = Callable[..., subprocess.CompletedProcess[str]]


def installed_helper_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Project Brain"
        / "bin"
        / "project-brain"
    )


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    label: str
    program_arguments: tuple[str, ...]
    plist_path: Path
    stdout_path: Path
    stderr_path: Path
    start_interval: int | None = None
    keep_alive: bool = False

    def plist(self, runtime: RuntimePaths) -> dict[str, Any]:
        value: dict[str, Any] = {
            "Label": self.label,
            "ProgramArguments": list(self.program_arguments),
            "RunAtLoad": True,
            "ProcessType": "Background",
            "WorkingDirectory": str(runtime.root),
            "StandardOutPath": str(self.stdout_path),
            "StandardErrorPath": str(self.stderr_path),
            "ThrottleInterval": 10,
            "EnvironmentVariables": {"PATH": LAUNCHD_TOOL_PATH},
        }
        if self.start_interval is not None:
            value["StartInterval"] = self.start_interval
        if self.keep_alive:
            value["KeepAlive"] = True
        return value


class ServiceManager:
    """Generate and apply only the two fixed Product Brain launchd services."""

    def __init__(
        self,
        runtime: RuntimePaths,
        *,
        helper_path: str | Path | None = None,
        launch_agents_dir: str | Path | None = None,
        runner: Runner | None = None,
        uid: int | None = None,
    ) -> None:
        raw_helper = Path(helper_path or installed_helper_path()).expanduser()
        if not raw_helper.is_absolute():
            raise ServiceError("Core helper path must be absolute")
        raw_launch_agents = Path(
            launch_agents_dir or (Path.home() / "Library" / "LaunchAgents")
        ).expanduser()
        if not raw_launch_agents.is_absolute():
            raise ServiceError("LaunchAgents path must be absolute")
        self.runtime = runtime
        self.helper_path = raw_helper.resolve()
        self.launch_agents_dir = raw_launch_agents.resolve()
        self.runner = runner or subprocess.run
        self.uid = os.getuid() if uid is None else uid

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    def specs(self) -> tuple[ServiceSpec, ServiceSpec]:
        helper = str(self.helper_path)
        runtime = str(self.runtime.root)
        worker = ServiceSpec(
            name="worker",
            label=WORKER_LABEL,
            program_arguments=(
                helper,
                "--runtime-root",
                runtime,
                "apply",
                "--json",
            ),
            plist_path=self.launch_agents_dir / f"{WORKER_LABEL}.plist",
            stdout_path=self.runtime.logs_dir / "worker.stdout.log",
            stderr_path=self.runtime.logs_dir / "worker.stderr.log",
            start_interval=30,
        )
        mcp = ServiceSpec(
            name="mcp",
            label=MCP_LABEL,
            program_arguments=(
                helper,
                "--runtime-root",
                runtime,
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "7677",
            ),
            plist_path=self.launch_agents_dir / f"{MCP_LABEL}.plist",
            stdout_path=self.runtime.logs_dir / "mcp.stdout.log",
            stderr_path=self.runtime.logs_dir / "mcp.stderr.log",
            keep_alive=True,
        )
        return worker, mcp

    def _validate_helper(self) -> None:
        if (
            not self.helper_path.is_file()
            or self.helper_path.is_symlink()
            or not os.access(self.helper_path, os.X_OK)
        ):
            raise ServiceError(
                f"Core helper is missing, linked, or not executable: {self.helper_path}"
            )

    def plan(self) -> dict[str, Any]:
        """Return a read-only plan; do not create runtime or launchd paths."""
        self._validate_helper()
        return {
            "status": "planned",
            "helper_version_check": [str(self.helper_path), "--version"],
            "services": [
                {
                    "name": spec.name,
                    "label": spec.label,
                    "installed": spec.plist_path.is_file(),
                    "program_arguments": list(spec.program_arguments),
                    "plist_path": str(spec.plist_path),
                }
                for spec in self.specs()
            ],
            "runtime_preserved_on_uninstall": True,
        }

    @staticmethod
    def _write_private_plist(path: Path, value: dict[str, Any]) -> None:
        data = plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            ServiceManager._fsync_directory(path.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _launchctl(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.runner(
            [LAUNCHCTL, *arguments],
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def _command_error(action: str, result: subprocess.CompletedProcess[str]) -> ServiceError:
        detail = (result.stderr or result.stdout or "launchctl failed").strip()[:1000]
        return ServiceError(f"{action} failed: {detail}")

    def install(self) -> dict[str, Any]:
        self._validate_helper()
        self.runtime.logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.runtime.logs_dir, 0o700)
        self.launch_agents_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for spec in self.specs():
            self._write_private_plist(spec.plist_path, spec.plist(self.runtime))
            self._launchctl("bootout", self.domain, spec.label)
            result = self._launchctl("bootstrap", self.domain, str(spec.plist_path))
            if result.returncode != 0:
                raise self._command_error(f"install {spec.name}", result)
        return {
            "status": "installed",
            "services": [spec.name for spec in self.specs()],
            "runtime_preserved": True,
        }

    def start(self) -> dict[str, Any]:
        for spec in self.specs():
            if not spec.plist_path.is_file():
                raise ServiceError(f"Service is not installed: {spec.name}")
            loaded = self._launchctl("print", f"{self.domain}/{spec.label}")
            if loaded.returncode != 0:
                result = self._launchctl("bootstrap", self.domain, str(spec.plist_path))
                if result.returncode != 0:
                    raise self._command_error(f"start {spec.name}", result)
            result = self._launchctl("kickstart", "-k", f"{self.domain}/{spec.label}")
            if result.returncode != 0:
                raise self._command_error(f"start {spec.name}", result)
        return {"status": "started", "services": [spec.name for spec in self.specs()]}

    def stop(self) -> dict[str, Any]:
        for spec in self.specs():
            self._launchctl("bootout", self.domain, spec.label)
        return {"status": "stopped", "services": [spec.name for spec in self.specs()]}

    def restart(self) -> dict[str, Any]:
        self.stop()
        self.start()
        return {"status": "restarted", "services": [spec.name for spec in self.specs()]}

    def uninstall(self) -> dict[str, Any]:
        removed: list[str] = []
        for spec in self.specs():
            self._launchctl("bootout", self.domain, spec.label)
            if spec.plist_path.is_file():
                spec.plist_path.unlink()
                removed.append(spec.name)
        if self.launch_agents_dir.is_dir():
            self._fsync_directory(self.launch_agents_dir)
        return {
            "status": "uninstalled",
            "removed": removed,
            "runtime_preserved": True,
        }

    def status(self) -> dict[str, Any]:
        services = [self._service_status(spec) for spec in self.specs()]
        states = {item["state"] for item in services}
        if states == {"running"}:
            aggregate = "healthy"
        elif "unhealthy" in states:
            aggregate = "unhealthy"
        elif states == {"not_installed"}:
            aggregate = "not_installed"
        else:
            aggregate = "stopped"
        return {
            "status": aggregate,
            "helper_executable": self.helper_path.is_file()
            and os.access(self.helper_path, os.X_OK),
            "services": services,
        }

    def _service_status(self, spec: ServiceSpec) -> dict[str, Any]:
        installed = spec.plist_path.is_file()
        result = self._launchctl("print", f"{self.domain}/{spec.label}")
        output = (result.stdout or "").lower()
        last_exit = re.search(r"last exit code\s*=\s*(-?\d+)", output)
        exit_code = int(last_exit.group(1)) if last_exit else None
        if result.returncode != 0:
            state = "stopped" if installed else "not_installed"
        elif "state = running" in output:
            state = "running"
        elif exit_code not in (None, 0):
            state = "unhealthy"
        else:
            state = "stopped"
        return {
            "name": spec.name,
            "label": spec.label,
            "state": state,
            "installed": installed,
            "last_exit_code": exit_code,
        }
