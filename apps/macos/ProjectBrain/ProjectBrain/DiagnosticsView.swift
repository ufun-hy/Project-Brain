import AppKit
import ProjectBrainKit
import SwiftUI
import UniformTypeIdentifiers

struct DiagnosticsView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Text("Diagnostics").font(.largeTitle.bold())
                    Spacer()
                    Button("Run checks") { model.refresh() }.buttonStyle(.borderedProminent)
                    Button("Export redacted report…", action: export)
                }

                GroupBox("Core and runtime") {
                    VStack(alignment: .leading, spacing: 10) {
                        diagnosticRow(
                            name: "Managed Core helper",
                            passed: model.services?.helperExecutable == true,
                            detail: model.services?.helperExecutable == true ? "Executable and managed" : "Missing or not executable"
                        )
                        ForEach(model.health?.checks ?? []) { check in
                            diagnosticRow(name: check.name, passed: check.passed, detail: check.detail)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Background services and loopback MCP") {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.services?.services ?? []) { service in
                            diagnosticRow(
                                name: service.label,
                                passed: service.state == "running" || (service.name == "worker" && service.state == "stopped" && service.lastExitCode == 0),
                                detail: "state=\(service.state), last_exit=\(service.lastExitCode.map(String.init) ?? "none")"
                            )
                        }
                        diagnosticRow(
                            name: "MCP loopback endpoint",
                            passed: model.connection.localMCPStatus == "running",
                            detail: model.connection.localMCPStatus == "running"
                                ? "launchd reports the loopback-only service running; transport acceptance remains pending"
                                : "local MCP service is not running"
                        )
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Task and worktree attention") {
                    VStack(alignment: .leading, spacing: 10) {
                        diagnosticRow(
                            name: "Recovery-blocked tasks",
                            passed: !model.tasks.contains { $0.status == .recoveryBlocked },
                            detail: "\(model.tasks.filter { $0.status == .recoveryBlocked }.count) require operator inspection"
                        )
                        diagnosticRow(
                            name: "Failed tasks",
                            passed: !model.tasks.contains { $0.status.needsAttention },
                            detail: "\(model.tasks.filter { $0.status.needsAttention }.count) need attention"
                        )
                        Text("Worktree cleanup is never exposed as a blind repair action. Failure evidence must remain available before any Core-controlled cleanup.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("External connection readiness") {
                    VStack(alignment: .leading, spacing: 10) {
                        diagnosticRow(
                            name: "Tunnel configuration",
                            passed: model.connection.tunnelConfigured,
                            detail: model.connection.tunnelConfigured ? "credential stored in Keychain" : "not configured"
                        )
                        diagnosticRow(
                            name: "ChatGPT external acceptance",
                            passed: model.connection.externalAcceptance == .passed,
                            detail: model.connection.externalAcceptance.title
                        )
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(28)
            .frame(maxWidth: 900, alignment: .leading)
        }
    }

    private func diagnosticRow(name: String, passed: Bool, detail: String) -> some View {
        HStack(alignment: .top) {
            Image(systemName: passed ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(passed ? .green : .orange)
            VStack(alignment: .leading) {
                Text(name).font(.headline)
                Text(SecretRedactor.redact(detail)).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func export() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "project-brain-diagnostics.json"
        panel.allowedContentTypes = [.json]
        if panel.runModal() == .OK, let url = panel.url { model.exportDiagnostics(to: url) }
    }
}
