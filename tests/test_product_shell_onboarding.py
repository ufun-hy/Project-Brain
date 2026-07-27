from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path


class ProductShellOnboardingSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_onboarding_errors_are_rendered_inside_sheet_with_recovery_actions(
        self,
    ) -> None:
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

    def test_build10_preflight_cannot_be_mistaken_for_distribution(self) -> None:
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
        verifier = (self.root / "scripts/verify-rc-artifact.py").read_text(
            encoding="utf-8"
        )
        layout_verifier = (
            self.root / "scripts/verify-rc-dmg-layout.sh"
        ).read_text(encoding="utf-8")
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        for source in (build, verifier, workflow):
            self.assertIn("Project-Brain-Build10-Preflight-Unsigned-arm64", source)
            self.assertNotIn("Project-Brain-Local-Tasks-Build8-arm64", source)
            self.assertNotIn("Project-Brain-RC1-Build7-arm64", source)
        self.assertIn("APP_BUILD=10", build)
        self.assertIn('"distribution_eligible": False', build)
        self.assertIn('manifest["app"]["build"] == "10"', verifier)
        self.assertIn('Info.plist\")" = "10"', layout_verifier)
        self.assertNotIn("actions/upload-artifact", workflow)

    def test_build10_release_is_manual_exact_sha_and_fail_closed_on_secrets(
        self,
    ) -> None:
        workflow = (self.root / ".github/workflows/macos-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("release_sha:", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$RELEASE_SHA"', workflow)
        self.assertIn("environment: macos-release", workflow)
        for secret in (
            "DEVELOPER_ID_APPLICATION_P12_BASE64",
            "DEVELOPER_ID_APPLICATION_P12_PASSWORD",
            "DEVELOPER_ID_APPLICATION_IDENTITY",
            "APPLE_TEAM_ID",
            "APPLE_NOTARY_KEY_P8_BASE64",
            "APPLE_NOTARY_KEY_ID",
            "APPLE_NOTARY_ISSUER_ID",
        ):
            self.assertIn(f"secrets.{secret}", workflow)
        self.assertIn("scripts/build-notarized-release-artifact.sh", workflow)
        self.assertIn("scripts/verify-notarized-release-artifact.py", workflow)
        self.assertIn("scripts/verify-notarized-gatekeeper.sh", workflow)
        self.assertIn("name: Project-Brain-Build10-arm64", workflow)
        self.assertNotIn("Project-Brain-Build9", workflow)

    def test_build10_signs_inside_out_and_notarizes_app_and_dmg(self) -> None:
        release = (
            self.root / "scripts/build-notarized-release-artifact.sh"
        ).read_text(encoding="utf-8")
        helper_sign = release.index('"$APP_HELPER"\n\nAPP_MAIN=')
        app_sign = release.index('"$APP"\n\n/usr/bin/codesign --verify')
        app_notary = release.index(
            '/usr/bin/xcrun notarytool submit "$APP_NOTARY_ZIP"'
        )
        app_staple = release.index('/usr/bin/xcrun stapler staple "$APP"')
        dmg_create = release.index("/usr/bin/hdiutil create")
        dmg_sign = release.index('"$DMG"\n/usr/bin/codesign --verify')
        dmg_notary = release.index('/usr/bin/xcrun notarytool submit "$DMG"')
        dmg_staple = release.index('/usr/bin/xcrun stapler staple "$DMG"')
        self.assertLess(
            helper_sign,
            app_sign,
        )
        self.assertLess(app_sign, app_notary)
        self.assertLess(app_notary, app_staple)
        self.assertLess(app_staple, dmg_create)
        self.assertLess(dmg_create, dmg_sign)
        self.assertLess(dmg_sign, dmg_notary)
        self.assertLess(dmg_notary, dmg_staple)
        self.assertGreaterEqual(release.count("--options runtime"), 2)
        self.assertGreaterEqual(release.count("--timestamp"), 3)
        self.assertIn('/usr/bin/file -b "$NESTED_EXECUTABLE"', release)
        self.assertIn('-name "*.framework"', release)
        self.assertIn('-name "*.xpc"', release)
        self.assertIn('-name "*.appex"', release)
        self.assertNotRegex(
            release,
            re.compile(r"codesign\s+\\\\\n(?:.*\\\\\n){0,8}\s+--deep", re.MULTILINE),
        )
        self.assertIn("refusing to overwrite immutable artifacts", release)
        self.assertNotIn("spctl --master-disable", release)
        self.assertNotIn("xattr -dr", release)

    def test_build10_manifest_keeps_fresh_mac_and_external_acceptance_pending(
        self,
    ) -> None:
        release = (
            self.root / "scripts/build-notarized-release-artifact.sh"
        ).read_text(encoding="utf-8")
        verifier = (
            self.root / "scripts/verify-notarized-release-artifact.py"
        ).read_text(encoding="utf-8")
        gatekeeper = (
            self.root / "scripts/verify-notarized-gatekeeper.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"artifact_classification": '
            '"developer_id_notarized_release_candidate"',
            release,
        )
        self.assertIn("developer_id_notarized_release_candidate", verifier)
        self.assertIn('"distribution_eligible": False', release)
        self.assertIn('manifest["distribution_eligible"] is False', verifier)
        for source in (release, verifier):
            self.assertIn('"fresh_mac_quarantine_acceptance": "pending_manual"', source)
            self.assertIn("pending_user_credentials_and_actions", source)
        self.assertIn("xattr -w", gatekeeper)
        self.assertNotIn("xattr -dr", gatekeeper)
        self.assertIn("Fresh-Mac browser-download GUI acceptance remains pending", gatekeeper)

    def test_build10_enables_hardened_runtime_and_version_is_distinct(self) -> None:
        project = (self.root / "apps/macos/ProjectBrain/project.yml").read_text(
            encoding="utf-8"
        )
        xcode_project = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain.xcodeproj/project.pbxproj"
        ).read_text(encoding="utf-8")
        self.assertIn("MARKETING_VERSION: 0.8.0", project)
        self.assertIn("CURRENT_PROJECT_VERSION: 10", project)
        self.assertIn("ENABLE_HARDENED_RUNTIME: YES", project)
        self.assertEqual(xcode_project.count("CURRENT_PROJECT_VERSION = 10;"), 2)
        self.assertEqual(xcode_project.count("MARKETING_VERSION = 0.8.0;"), 2)
        self.assertEqual(xcode_project.count("ENABLE_HARDENED_RUNTIME = YES;"), 2)

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
        project = (self.root / "apps/macos/ProjectBrain/project.yml").read_text(
            encoding="utf-8"
        )
        package = (self.root / "apps/macos/ProjectBrain/Package.swift").read_text(
            encoding="utf-8"
        )
        xcode_project = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain.xcodeproj/project.pbxproj"
        ).read_text(encoding="utf-8")
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
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
            (self.root / "apps/macos/ProjectBrain/ProjectBrain/Info.plist").read_bytes()
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
        self.assertIn("Darwin._exit(EXIT_SUCCESS)", coordinator)
        self.assertIn(
            'INSTALLED_APP="/Applications/Project Brain.app"', instance_verifier
        )
        self.assertIn("management_window_count", instance_verifier)

    def test_final_app_embeds_and_executes_shared_cli_contract(self) -> None:
        project = (self.root / "apps/macos/ProjectBrain/project.yml").read_text(
            encoding="utf-8"
        )
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
        verifier = (
            self.root / "scripts/verify-bundled-helper-onboarding.py"
        ).read_text(encoding="utf-8")
        self.assertIn("project-brain-cli-contract.json", project)
        self.assertIn("verify-bundled-helper-onboarding.py", workflow + build)
        self.assertIn('"--resolve-existing"', verifier)
        self.assertIn('existing_plan["plan"]["action"] == "use_existing"', verifier)
        self.assertIn('update_plan["plan"]["action"] == "update"', verifier)

    def test_local_task_ui_has_review_first_entries_and_no_control_fields(self) -> None:
        menu = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/MenuBarView.swift"
        ).read_text(encoding="utf-8")
        center = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/TaskCenterView.swift"
        ).read_text(encoding="utf-8")
        form = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/NewTaskView.swift"
        ).read_text(encoding="utf-8")
        self.assertIn('Button("New Task…")', menu)
        self.assertIn('Button("Create Task")', center)
        self.assertIn('Button("Review Execution Plan")', form)
        self.assertIn('Button("Confirm and Create Task")', form)
        self.assertIn('accessibilityIdentifier("local-task-inline-error")', form)
        self.assertIn('Button("Open Diagnostics")', form)
        self.assertIn("(10...8_000).contains", form)
        self.assertIn("criteriaCharacterCount <= 8_000", form)
        self.assertIn("LocalTaskType.analysis", form)
        self.assertIn("LocalTaskType.implement", form)
        self.assertIn(
            "model.localTaskPhase.isBusy || !plan.plan.readiness.ready", form
        )
        self.assertIn("LocalTaskOperationPhase", (
            self.root / "apps/macos/ProjectBrain/ProjectBrainKit/CoreModels.swift"
        ).read_text(encoding="utf-8"))
        self.assertIn('DisclosureGroup("Technical details"', form)
        self.assertIn('LabeledContent("Plan fingerprint"', form)
        self.assertNotIn('LabeledContent("Plan token"', form)
        self.assertNotIn("plan.planToken)", form)
        self.assertNotIn('TextField("Command', form)
        self.assertNotIn('TextField("argv', form)
        self.assertNotIn('TextField("cwd', form)
        self.assertNotIn('TextField("Environment', form)

    def test_guided_first_run_and_localizations_are_packaged(self) -> None:
        center = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/TaskCenterView.swift"
        ).read_text(encoding="utf-8")
        package = (self.root / "apps/macos/ProjectBrain/Package.swift").read_text(
            encoding="utf-8"
        )
        project = (self.root / "apps/macos/ProjectBrain/project.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('alert("Your first project is ready"', center)
        self.assertIn('Button("Create First Task")', center)
        self.assertIn('Button("Not now"', center)
        self.assertIn('defaultLocalization: "en"', package)
        self.assertIn("resources:", project)
        for locale in ("en", "zh-Hans"):
            strings = (
                self.root
                / f"apps/macos/ProjectBrain/ProjectBrain/Resources/{locale}.lproj/Localizable.strings"
            )
            self.assertTrue(strings.is_file())
            content = strings.read_text(encoding="utf-8")
            self.assertIn('"New Task…"', content)
            self.assertIn('"Your first project is ready"', content)
            self.assertIn('"Check the task goal"', content)
            self.assertIn('"Execution plan changed"', content)
            self.assertIn('"Building execution plan…"', content)
            self.assertIn('"Creating task record…"', content)
        chinese = (
            self.root
            / "apps/macos/ProjectBrain/ProjectBrain/Resources/zh-Hans.lproj/Localizable.strings"
        ).read_text(encoding="utf-8")
        self.assertIn('"Check the task goal" = "请检查任务目标";', chinese)
        self.assertIn('"Execution plan changed" = "执行计划已变化";', chinese)

    def test_final_dmg_runs_embedded_helper_local_task_end_to_end(self) -> None:
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        verifier = (
            self.root / "scripts/verify-bundled-helper-local-task.py"
        ).read_text(encoding="utf-8")
        self.assertIn("verify-bundled-helper-local-task.py", workflow)
        self.assertIn("tasks", verifier)
        self.assertIn("local-plan", verifier)
        self.assertIn("PROJECT_BRAIN_RELEASE_PROBE_MODE", verifier)
        self.assertIn("createLocalTask", (
            self.root
            / "apps/macos/ProjectBrain/ProjectBrain/ReleaseLocalTaskAppProbe.swift"
        ).read_text(encoding="utf-8"))
        self.assertIn("PROJECT_BRAIN_RELEASE_APP_PROBE", verifier)
        self.assertIn("exact_goal", verifier)
        self.assertIn("helper_cold_start", verifier)
        self.assertIn("post_create_ui_update", verifier)
        self.assertIn('"expected_plan_hash"', (
            self.root / "src/project_brain/local_tasks.py"
        ).read_text(encoding="utf-8"))
        self.assertIn('task["status"] == "completed"', verifier)
        self.assertNotIn("tunnel", verifier.lower())

    def test_create_closes_sheet_before_single_background_detail_refresh(self) -> None:
        app_model = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/AppModel.swift"
        ).read_text(encoding="utf-8")
        create_flow = app_model.split("func createLocalTask()", 1)[1].split(
            "func cancelLocalTaskSheet()", 1
        )[0]
        self.assertIn("isNewTaskPresented = false", create_flow)
        self.assertIn("schedulePostCreateRefresh(", create_flow)
        self.assertNotIn("backend.refresh", create_flow)
        self.assertIn('localTaskTimingMS["create_click_feedback"]', create_flow)
        self.assertIn('localTaskTimingMS["post_create_ui_update"]', create_flow)
        refresh_flow = app_model.split("func schedulePostCreateRefresh", 1)[1]
        self.assertEqual(refresh_flow.count("backend.task(taskID)"), 1)
        self.assertNotIn("backend.refresh", refresh_flow)

    def test_opening_task_sheet_resets_prior_timing_evidence(self) -> None:
        app_model = (
            self.root / "apps/macos/ProjectBrain/ProjectBrain/AppModel.swift"
        ).read_text(encoding="utf-8")
        open_flow = app_model.split("func openNewTask", 1)[1].split(
            "func updateLocalTaskType", 1
        )[0]
        self.assertLess(open_flow.index("localTaskTimingMS = [:]"), open_flow.index(".checkingProject"))
        self.assertIn('localTaskTimingMS["open_sheet"]', open_flow)

    def test_dmg_contains_applications_link_and_visible_installation_guide(
        self,
    ) -> None:
        build = (self.root / "scripts/build-rc-artifact.sh").read_text(encoding="utf-8")
        workflow = (self.root / ".github/workflows/core-tests.yml").read_text(
            encoding="utf-8"
        )
        verifier = (self.root / "scripts/verify-rc-dmg-layout.sh").read_text(
            encoding="utf-8"
        )
        guide = (
            self.root / "packaging/dmg/把 Project Brain.app 拖到 Applications 安装.txt"
        ).read_text(encoding="utf-8")
        self.assertIn('/bin/ln -s /Applications "$TEMP_ROOT/dmg/Applications"', build)
        self.assertIn("verify-rc-dmg-layout.sh", workflow)
        self.assertIn("LSMultipleInstancesProhibited", verifier)
        self.assertIn("拖到旁边的“Applications”", guide)


if __name__ == "__main__":
    unittest.main()
