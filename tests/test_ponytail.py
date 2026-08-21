from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from project_brain.errors import InvalidTaskError
from project_brain.ponytail import codex_environment, codex_prompt, resolve_ponytail_mode


class PonytailPolicyTests(unittest.TestCase):
    def test_defaults_to_lite(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_ponytail_mode({"payload": {}}), "lite")
            self.assertEqual(
                codex_prompt({"payload": {}}, "Implement it."),
                "@ponytail lite\n\nImplement it.",
            )

    def test_host_default_can_be_changed(self) -> None:
        with patch.dict(
            os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "full"}, clear=True
        ):
            self.assertEqual(resolve_ponytail_mode({"payload": {}}), "full")
            self.assertEqual(
                codex_prompt({"payload": {}}, "Implement it."),
                "@ponytail full\n\nImplement it.",
            )

    def test_task_override_wins(self) -> None:
        with patch.dict(
            os.environ, {"PROJECT_BRAIN_PONYTAIL_MODE": "lite"}, clear=True
        ):
            task = {"payload": {"ponytail_mode": "ultra"}}
            self.assertEqual(resolve_ponytail_mode(task), "ultra")
            self.assertEqual(codex_environment(task)["PONYTAIL_DEFAULT_MODE"], "ultra")
            self.assertEqual(
                codex_prompt(task, "Simplify it."),
                "@ponytail ultra\n\nSimplify it.",
            )

    def test_off_is_explicitly_forwarded(self) -> None:
        task = {"payload": {"ponytail_mode": "off"}}
        self.assertEqual(codex_prompt(task, "Analyze it."), "@ponytail off\n\nAnalyze it.")

    def test_invalid_mode_fails_closed(self) -> None:
        with self.assertRaisesRegex(InvalidTaskError, "ponytail_mode must be one of"):
            resolve_ponytail_mode({"payload": {"ponytail_mode": "maximum"}})


if __name__ == "__main__":
    unittest.main()
