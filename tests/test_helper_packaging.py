from __future__ import annotations

import unittest
from pathlib import Path


class HelperPackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_pyinstaller_build_is_single_file_and_excludes_cli_extras(self) -> None:
        spec = (self.root / "packaging/pyinstaller/project-brain.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn('name="project-brain"', spec)
        self.assertIn('"cli_contract.json"', spec)
        self.assertNotIn("COLLECT(", spec)
        self.assertIn('"mcp.cli"', spec)
        self.assertIn('"pkg_resources"', spec)

    def test_build_script_validates_executable_and_exact_version(self) -> None:
        script = (self.root / "scripts/build-macos-helper.sh").read_text(encoding="utf-8")
        self.assertIn('test -x "$HELPER"', script)
        self.assertIn('"project-brain 0.7.0"', script)
        self.assertIn('"$HELPER" projects add --help', script)
        self.assertIn("cli-contract --json", script)
        self.assertNotIn("zsh -lc", script)
        self.assertNotIn("bash -lc", script)


if __name__ == "__main__":
    unittest.main()
