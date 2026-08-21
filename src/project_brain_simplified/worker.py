from __future__ import annotations

import argparse
import os
import traceback

from .runner import execute_task
from .runtime import RuntimePaths
from .store import Store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    runtime = RuntimePaths.from_value(args.runtime_root).ensure()
    store = Store(runtime.database)
    store.initialize()
    try:
        store.claim_task(args.task_id, pid=os.getpid())
    except Exception:
        # A second launcher must never be able to fail or take over the first
        # worker's task. The claim gate is the complete duplicate-dispatch
        # decision; leave the existing task untouched.
        return 1
    try:
        result = execute_task(store, runtime, args.task_id)
    except Exception as exc:
        # Convert ordinary worker crashes into a terminal failure. A later
        # observer can also fail a process that dies before this handler runs.
        try:
            result = store.fail_running_task(
                args.task_id,
                error=f"Worker crashed; task was not retried: {exc}\n{traceback.format_exc()}",
            )
        except Exception:
            return 1
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
