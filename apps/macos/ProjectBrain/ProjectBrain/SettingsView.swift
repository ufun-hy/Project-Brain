import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Form {
            Section("Managed Core") {
                LabeledContent("Runtime", value: "~/.project-brain")
                LabeledContent("Helper", value: model.services?.helperExecutable == true ? "Installed" : "Needs repair")
                Button("Reinstall or upgrade bundled helper") {
                    model.prepareRuntime(advanceOnboarding: false)
                }
            }
            Section("Background services") {
                HStack {
                    Button("Install") { model.performService(.install) }
                    Button("Restart") { model.performService(.restart) }
                    Button("Uninstall", role: .destructive) { model.performService(.uninstall) }
                }
                Text("Uninstall removes only the two launchd services. Runtime data, project registration, task history, and repositories are preserved.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Onboarding") {
                Button("Run onboarding again") { model.restartOnboarding() }
                Text("This does not delete or reset the existing runtime.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Application") {
                Button("Quit Project Brain", role: .destructive) {
                    model.quitApplication()
                }
                .accessibilityIdentifier("settings-quit-project-brain")
                Text("Stops this app without deleting projects, tasks, or runtime data.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Safety boundaries") {
                Label("No arbitrary shell, argv, SQL, merge, or Git cleanup entry points", systemImage: "checkmark.shield")
                Label("Runtime deletion is intentionally unavailable in Product Shell v1", systemImage: "externaldrive.badge.xmark")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Settings")
    }
}
