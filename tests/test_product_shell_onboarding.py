from __future__ import annotations

import plistlib
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

    def test_build7_artifact_names_cannot_overwrite_build6_names(self) -> None:
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
        verifier = (self.root / "scripts/verify-rc-artifact.py").read_text(
            encoding="utf-8"
        )
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        for source in (build, verifier, workflow):
            self.assertIn("Project-Brain-RC1-Build7-arm64", source)
            self.assertNotIn("Project-Brain-RC1-Build6-arm64", source)
        self.assertIn("APP_BUILD=7", build)
        self.assertIn('manifest["app"]["build"] == "7"', verifier)

    def test_quit_is_visible_in_menu_bar_and_settings(self) -> None:
        menu = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/MenuBarView.swift"
        ).read_text(encoding="utf-8")
        settings = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/SettingsView.swift"
        ).read_text(encoding="utf-8")
        model = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/AppModel.swift"
        ).read_text(encoding="utf-8")
        self.assertIn('Button("Quit Project Brain", role: .destructive)', menu)
        self.assertIn('Button("Quit Project Brain", role: .destructive)', settings)
        self.assertIn("func quitApplication()", model)
        self.assertIn("NSApplication.shared.terminate(nil)", model)

    def test_release_app_is_single_instance(self) -> None:
        project = (
            self.root / "apps/macos/ProjectBrain/project.yml"
        ).read_text(encoding="utf-8")
        package = (
            self.root / "apps/macos/ProjectBrain/Package.swift"
        ).read_text(encoding="utf-8")
        xcode_project = (
            self.root
            / "apps/macos/ProjectBrain/ProjectBrain.xcodeproj/project.pbxproj"
        ).read_text(encoding="utf-8")
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(
            encoding="utf-8"
        )
        app = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/ProjectBrainApp.swift"
        ).read_text(encoding="utf-8")
        coordinator = (
            self.root
            / "apps/macos/ProjectBrain/ProjectBrain/ApplicationInstanceCoordinator.swift"
        ).read_text(encoding="utf-8")
        instance_verifier = (
            self.root / "scripts/verify-final-app-single-instance.sh"
        ).read_text(encoding="utf-8")
        info_plist = plistlib.loads(
            (
                self.root
                / "apps/macos/ProjectBrain/ProjectBrain/Info.plist"
            ).read_bytes()
        )
        self.assertIn("INFOPLIST_FILE: ProjectBrain/Info.plist", project)
        self.assertIn('exclude: ["Info.plist"]', package)
        self.assertEqual(
            xcode_project.count("INFOPLIST_FILE = ProjectBrain/Info.plist;"),
            2,
        )
        self.assertIs(info_plist["LSMultipleInstancesProhibited"], True)
        self.assertIn("Print :LSMultipleInstancesProhibited", build)
        self.assertIn('Window("Project Brain", id: "management")', app)
        self.assertNotIn('WindowGroup("Project Brain", id: "management")', app)
        self.assertIn("UserProcessLock.acquire", coordinator)
        self.assertIn('INSTALLED_APP="/Applications/Project Brain.app"', instance_verifier)
        self.assertIn("management_window_count", instance_verifier)

    def test_final_app_embeds_and_executes_shared_cli_contract(self) -> None:
        project = (self.root / "apps/macos/ProjectBrain/project.yml").read_text(
            encoding="utf-8"
        )
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(
            encoding="utf-8"
        )
        verifier = (
            self.root / "scripts/verify-bundled-helper-onboarding.py"
        ).read_text(encoding="utf-8")
        self.assertIn("project-brain-cli-contract.json", project)
        self.assertIn("verify-bundled-helper-onboarding.py", workflow + build)
        self.assertIn('"--resolve-existing"', verifier)
        self.assertIn('existing_plan["plan"]["action"] == "use_existing"', verifier)
        self.assertIn('update_plan["plan"]["action"] == "update"', verifier)

    def test_dmg_contains_applications_link_and_visible_installation_guide(
        self,
    ) -> None:
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(
            encoding="utf-8"
        )
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        verifier = (self.root / "scripts/verify-rc-dmg-layout.sh").read_text(
            encoding="utf-8"
        )
        guide = (
            self.root
            / "packaging/dmg/把 Project Brain.app 拖到 Applications 安装.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '/bin/ln -s /Applications "$TEMP_ROOT/dmg/Applications"', build
        )
        self.assertIn("verify-rc-dmg-layout.sh", workflow)
        self.assertIn("LSMultipleInstancesProhibited", verifier)
        self.assertIn("拖到旁边的“Applications”", guide)


if __name__ == "__main__":
    unittest.main()
