from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_brain.build_info import core_build_sha


class BuildInfoTests(unittest.TestCase):
    def test_valid_packaged_build_sha_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build-info.json").write_text(
                json.dumps({"build_sha": "a" * 40}), encoding="utf-8"
            )
            with patch("project_brain.build_info.resources.files", return_value=root):
                self.assertEqual(core_build_sha(), "a" * 40)

    def test_missing_or_invalid_build_info_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("project_brain.build_info.resources.files", return_value=root):
                self.assertIsNone(core_build_sha())
            (root / "build-info.json").write_text(
                json.dumps({"build_sha": "not-a-sha"}), encoding="utf-8"
            )
            with patch("project_brain.build_info.resources.files", return_value=root):
                self.assertIsNone(core_build_sha())


if __name__ == "__main__":
    unittest.main()
