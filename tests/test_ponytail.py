from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from project_brain.errors import InvalidTaskError
from project_brain.ponytail import codex_environment, resolve_ponytail_mode


class PonytailPolicyTests(unittest.TestCase):
    def test_defaults_to_lite(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_ponytail_mode({"payload": {}}), "lite")

    def test_host_default_can_be_changed(self) -> None:
        with patch.dict(
            os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "full"}, clear=True
        ):
            self.assertEqual(resolve_ponytail_mode({"payload": {}}), "full")

    def test_task_override_wins(self) -> None:
        with patch.dict(
            os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "lite"}, clear=True
        ):
            task = {"payload": {"ponytail_mode": "ultra"}}
            self.assertEqual(resolve_ponytail_mode(task), "ultra")
            self.assertEqual(codex_environment(task)["PONYTAIL_DEFAULT_MODE"], "ultra")

    def test_invalid_mode_fails_closed(self) -> None:
        with self.assertRaisesRegex(InvalidTaskError, "ponytail_mode must be one of"):
            resolve_ponytail_mode({"payload": {"ponytail_mode": "maximum"}})


if __name__ == "__main__":
    unittest.main()
