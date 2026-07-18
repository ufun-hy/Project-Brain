from __future__ import annotations

import unittest
from pathlib import Path


class ProductShellOnboardingSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_onboarding_errors_are_rendered_inside_sheet_with_recovery_actions(self) -> None:
        onboarding = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/OnboardingView.swift"
        ).read_text(encoding="utf-8")
        management = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/ManagementView.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("if let issue = model.issue", onboarding)
        self.assertIn('accessibilityIdentifier("onboarding-inline-error")', onboarding)
        self.assertIn('Button("Use existing project")', onboarding)
        self.assertIn('Button("Choose other directory")', onboarding)
        self.assertIn('Button("Modify name")', onboarding)
        self.assertIn("model.onboarding.completed ? model.issue : nil", management)

    def test_build5_artifact_names_cannot_overwrite_build4_names(self) -> None:
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
        verifier = (self.root / "scripts/verify-rc-artifact.py").read_text(
            encoding="utf-8"
        )
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        for source in (build, verifier, workflow):
            self.assertIn("Project-Brain-RC1-Build5-arm64", source)
        self.assertIn("APP_BUILD=5", build)
        self.assertIn('{"build": "5", "version": "0.7.0"}', verifier)


if __name__ == "__main__":
    unittest.main()
