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
                            detail: model.services?.helperExecutable == true ? "Executable and managed" : "Missing or not executable",
                            severity: .error,
                            blocks: true,
                            repair: .reinstallHelper,
                            advice: "Reinstall the bundled helper from this app."
                        )
                        ForEach(model.health?.checks ?? []) { check in
                            diagnosticRow(
                                name: check.name,
                                passed: check.passed,
                                detail: check.detail,
                                severity: check.passed ? .info : .error,
                                blocks: !check.passed,
                                advice: "Resolve this local prerequisite, then run checks again."
                            )
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Background services and loopback MCP") {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.services?.services ?? []) { service in
                            diagnosticRow(
                                name: service.label,
                                passed: service.state == "running" || service.state == "healthy",
                                detail: "state=\(service.state), last_exit=\(service.lastExitCode.map(String.init) ?? "none")",
                                severity: .error,
                                blocks: service.name == "worker",
                                repair: .restartServices,
                                advice: "Restart the fixed Worker and MCP launchd services."
                            )
                        }
                        diagnosticRow(
                            name: "MCP loopback endpoint",
                            passed: model.connection.localMCPStatus == "running",
                            detail: model.connection.localMCPStatus == "running"
                                ? "launchd reports the loopback-only service running; transport acceptance remains pending"
                                : "local MCP service is not running",
                            severity: .warning,
                            blocks: false,
                            repair: .restartServices,
                            advice: "Restart MCP, then repeat the connection check."
                        )
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Task and worktree attention") {
                    VStack(alignment: .leading, spacing: 10) {
                        diagnosticRow(
                            name: "Recovery-blocked tasks",
                            passed: !model.tasks.contains { $0.status == .recoveryBlocked },
                            detail: "\(model.tasks.filter { $0.status == .recoveryBlocked }.count) require operator inspection",
                            severity: .error,
                            blocks: true,
                            advice: "Inspect the persisted agent identity and evidence before choosing a recovery action."
                        )
                        diagnosticRow(
                            name: "Failed tasks",
                            passed: !model.tasks.contains { $0.status.needsAttention },
                            detail: "\(model.tasks.filter { $0.status.needsAttention }.count) need attention",
                            severity: .warning,
                            blocks: false,
                            advice: "Open Task Center and follow each task's bounded next action."
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
                            detail: model.connection.tunnelConfigured ? "credential stored in Keychain" : "not configured",
                            severity: .warning,
                            blocks: false,
                            repair: .openConnectionCenter,
                            advice: "Configure the Tunnel credential in Connection Center when ready."
                        )
                        diagnosticRow(
                            name: "ChatGPT external acceptance",
                            passed: model.connection.externalAcceptance == .passed,
                            detail: model.connection.externalAcceptance.title,
                            severity: .warning,
                            blocks: false,
                            repair: .openConnectionCenter,
                            advice: "Run the real Tunnel and ChatGPT developer-mode acceptance flow."
                        )
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(28)
            .frame(maxWidth: 900, alignment: .leading)
        }
    }

    private func diagnosticRow(
        name: String,
        passed: Bool,
        detail: String,
        severity: DiagnosticSeverity,
        blocks: Bool,
        repair: DiagnosticRepairAction = .none,
        advice: String
    ) -> some View {
        HStack(alignment: .top) {
            Image(systemName: passed ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(passed ? .green : .orange)
            VStack(alignment: .leading) {
                Text(name).font(.headline)
                Text(SecretRedactor.redact(detail)).font(.caption).foregroundStyle(.secondary)
                if !passed {
                    Text("\(severity.rawValue.capitalized) · \(blocks ? "Blocks new task intake" : "Does not block task intake")")
                        .font(.caption.bold())
                    Text(advice).font(.caption).foregroundStyle(.secondary)
                    repairButton(repair)
                }
            }
        }
    }

    @ViewBuilder private func repairButton(_ action: DiagnosticRepairAction) -> some View {
        switch action {
        case .none:
            EmptyView()
        case .reinstallHelper:
            Button("Repair helper") { model.prepareRuntime(advanceOnboarding: false) }
                .buttonStyle(.link)
        case .restartServices:
            Button("Restart services") { model.performService(.restart) }
                .buttonStyle(.link)
        case .openConnectionCenter:
            Button("Open Connection Center") { model.selectedSection = .connection }
                .buttonStyle(.link)
        }
    }

    private func export() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "project-brain-diagnostics.json"
        panel.allowedContentTypes = [.json]
        if panel.runModal() == .OK, let url = panel.url { model.exportDiagnostics(to: url) }
    }
}
