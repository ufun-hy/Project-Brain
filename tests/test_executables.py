from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_brain.executables import LAUNCHD_TOOL_PATH, find_executable


class ExecutableDiscoveryTests(unittest.TestCase):
    def test_absolute_executable_is_canonicalized_and_missing_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "tool"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            self.assertEqual(find_executable(str(executable)), str(executable.resolve()))
            self.assertIsNone(find_executable(str(executable.with_name("missing"))))

    def test_launchd_path_is_fixed_and_does_not_accept_caller_environment(self) -> None:
        with patch.dict(os.environ, {"PATH": "/untrusted"}):
            self.assertEqual(
                LAUNCHD_TOOL_PATH,
                "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            )


if __name__ == "__main__":
    unittest.main()
