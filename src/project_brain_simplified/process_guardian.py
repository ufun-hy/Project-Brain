from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time


def _terminate_group(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 2

    # The parent sends the prompt through this pipe. Do not start Codex until
    # the prompt is fully received and the worker is still our parent. If the
    # worker dies before this point, no Codex process is ever started.
    input_data = sys.stdin.buffer.read()
    if os.getppid() != args.parent_pid:
        return 125

    try:
        codex: subprocess.Popen[bytes] | None = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        sys.stderr.write(f"Could not start process: {exc}\n")
        return 127

    def stop_on_parent_loss() -> None:
        while codex is not None and codex.poll() is None:
            if os.getppid() != args.parent_pid:
                _terminate_group(codex)
                return
            time.sleep(0.05)

    monitor = threading.Thread(target=stop_on_parent_loss, daemon=True)
    monitor.start()

    def handle_signal(signum: int, _frame: object) -> None:
        _terminate_group(codex)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        stdout, stderr = codex.communicate(input=input_data)
    except (BrokenPipeError, OSError):
        _terminate_group(codex)
        return 125
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.flush()
    return int(codex.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
