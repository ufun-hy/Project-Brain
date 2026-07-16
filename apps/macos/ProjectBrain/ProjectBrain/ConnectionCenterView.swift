import ProjectBrainKit
import SwiftUI

struct ConnectionCenterView: View {
    @ObservedObject var model: AppModel
    @State private var tunnelToken = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Connection Center").font(.largeTitle.bold())

                GroupBox("Local services") {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(model.services?.services ?? []) { service in
                            HStack {
                                Image(systemName: service.state == "running" ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(service.state == "running" ? .green : .secondary)
                                Text(service.name.capitalized)
                                Spacer()
                                Text(service.state.capitalized).foregroundStyle(.secondary)
                            }
                        }
                        HStack {
                            Button("Start") { model.performService(.start) }
                            Button("Stop") { model.performService(.stop) }
                            Button("Restart") { model.performService(.restart) }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("Secure MCP Tunnel") {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(
                            model.tunnelTokenConfigured ? "Token stored in Keychain" : "Token not configured",
                            systemImage: model.tunnelTokenConfigured ? "key.fill" : "key"
                        )
                        SecureField("Tunnel token", text: $tunnelToken)
                            .textFieldStyle(.roundedBorder)
                        HStack {
                            Button("Save to Keychain") {
                                model.saveTunnelToken(tunnelToken)
                                tunnelToken = ""
                            }.disabled(tunnelToken.isEmpty)
                            if model.tunnelTokenConfigured {
                                Button("Remove token", role: .destructive) { model.removeTunnelToken() }
                            }
                        }
                        Text("The token is never written to SQLite, launchd plists, logs, tasks, or diagnostic exports.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("ChatGPT workspace") {
                    VStack(alignment: .leading, spacing: 12) {
                        LabeledContent("Configuration") {
                            Text(model.connection.workspaceConfigured ? "Prepared" : "Not prepared")
                        }
                        LabeledContent("External acceptance") {
                            Text(model.connection.externalAcceptance.title)
                                .foregroundStyle(model.connection.externalAcceptance == .passed ? .green : .orange)
                        }
                        Button("Mark workspace configuration prepared") {
                            model.markWorkspaceConfigured()
                        }
                        Text("A real Secure MCP Tunnel + ChatGPT developer-mode task is required before acceptance can be marked passed. Local tests do not replace it.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(28)
            .frame(maxWidth: 820, alignment: .leading)
        }
    }
}
