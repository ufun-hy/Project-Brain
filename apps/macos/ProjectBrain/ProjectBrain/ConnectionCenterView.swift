import ProjectBrainKit
import SwiftUI

struct ConnectionCenterView: View {
    @ObservedObject var model: AppModel
    @State private var tunnelID = ""
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
                        LabeledContent("Local MCP endpoint") {
                            Text(TunnelClient.localMCPURL.absoluteString).textSelection(.enabled)
                        }
                        LabeledContent("Official tunnel-client") {
                            Text(model.connection.tunnelClientAvailable ? "Available" : "Not installed")
                                .foregroundStyle(model.connection.tunnelClientAvailable ? .green : .orange)
                        }
                        Label(
                            model.tunnelTokenConfigured ? "Token stored in Keychain" : "Token not configured",
                            systemImage: model.tunnelTokenConfigured ? "key.fill" : "key"
                        )
                        TextField("Tunnel ID (tunnel_ + 32 lowercase hex)", text: $tunnelID)
                            .textFieldStyle(.roundedBorder)
                        SecureField("Runtime API key", text: $tunnelToken)
                            .textFieldStyle(.roundedBorder)
                        HStack {
                            Button("Save and start") {
                                model.saveAndStartTunnel(tunnelID: tunnelID, token: tunnelToken)
                                tunnelToken = ""
                            }.disabled(
                                tunnelToken.isEmpty
                                    || !TunnelClient.isValidTunnelID(tunnelID)
                                    || !model.connection.tunnelClientAvailable
                            )
                            if model.tunnelTokenConfigured {
                                Button("Remove configuration", role: .destructive) {
                                    model.removeTunnelConfiguration()
                                }
                            }
                        }
                        HStack {
                            Button("Start") { model.startTunnel() }
                            Button("Stop") { model.stopTunnel() }
                            Button("Reconnect") { model.reconnectTunnel() }
                            Button("Check status") { model.checkTunnelStatus() }
                        }
                        .disabled(!model.connection.tunnelConfigured || !model.connection.tunnelClientAvailable)
                        Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
                            GridRow { Text("Process"); Text(model.connection.tunnelProcessRunning ? "Running" : "Stopped") }
                            GridRow { Text("Health"); Text(model.connection.tunnelHealthy ? "Healthy" : "Not healthy") }
                            GridRow { Text("Control plane"); Text(model.connection.tunnelReady ? "Ready" : "Not ready") }
                            GridRow { Text("Runtime state"); Text(model.connection.tunnelRuntimeState) }
                            GridRow { Text("Acceptance entry"); Text(model.connection.externalAcceptance.title) }
                        }
                        if let url = model.connection.tunnelUIURL.flatMap(URL.init(string:)) {
                            Link("Open local tunnel status UI", destination: url)
                        }
                        HStack {
                            Link("OpenAI Platform Tunnels", destination: URL(string: "https://platform.openai.com/settings/organization/tunnels")!)
                            Link("Official tunnel-client releases", destination: URL(string: "https://github.com/openai/tunnel-client/releases")!)
                        }
                        Text("The token is never written to SQLite, launchd plists, logs, tasks, or diagnostic exports.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }

                GroupBox("ChatGPT workspace") {
                    VStack(alignment: .leading, spacing: 12) {
                        LabeledContent("Configuration") {
                            Text(model.connection.workspaceConfiguration.rawValue)
                        }
                        LabeledContent("System verification") {
                            Text(model.connection.externalVerification.rawValue)
                        }
                        LabeledContent("External acceptance") {
                            Text(model.connection.externalAcceptance.title)
                                .foregroundStyle(model.connection.externalAcceptance == .passed ? .green : .orange)
                        }
                        Button("Declare workspace configuration prepared") {
                            model.markWorkspaceConfigured()
                        }
                        Text("This is an operator declaration only. A real Secure MCP Tunnel + ChatGPT developer-mode task is required before external verification can become passed. Local tests do not replace it.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(28)
            .frame(maxWidth: 820, alignment: .leading)
        }
        .onAppear { tunnelID = model.connection.tunnelID }
    }
}
