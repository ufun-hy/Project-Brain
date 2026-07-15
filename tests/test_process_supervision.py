from __future__ import annotations

import subprocess
import sys
import unittest

from project_brain.process_supervision import (
    ProcessIdentityState,
    capture_process_identity,
    inspect_agent_process_group,
    terminate_process_group,
)


class ProcessSupervisionTests(unittest.TestCase):
    def test_identity_mismatch_is_not_signalled(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
            text=True,
        )
        identity = capture_process_identity(child.pid, child.pid)
        self.assertIsNotNone(identity)
        wrong_identity = {**identity, "start_marker": f"{identity['start_marker']}-reused"}
        try:
            self.assertEqual(
                inspect_agent_process_group(child.pid, child.pid, identity),
                ProcessIdentityState.VERIFIED_ALIVE,
            )
            self.assertEqual(
                inspect_agent_process_group(child.pid, child.pid, wrong_identity),
                ProcessIdentityState.UNVERIFIED_ALIVE,
            )
            self.assertFalse(
                terminate_process_group(
                    child_pid=child.pid,
                    child_pgid=child.pid,
                    expected_identity=wrong_identity,
                    grace_seconds=0.1,
                )
            )
            self.assertIsNone(child.poll())
        finally:
            terminate_process_group(
                child_pid=child.pid,
                child_pgid=child.pid,
                expected_identity=identity,
                grace_seconds=0.1,
                process=child,
            )


if __name__ == "__main__":
    unittest.main()
