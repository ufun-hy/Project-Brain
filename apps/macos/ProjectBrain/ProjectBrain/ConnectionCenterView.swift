import AppKit
import ProjectBrainKit
import SwiftUI
import UniformTypeIdentifiers

struct ConnectionCenterView: View {
    @ObservedObject var model: AppModel
    @State private var tunnelID = ""
    @State private var tunnelToken = ""
    @State private var selectedAcceptanceProjectID = ""
    @State private var confirmTunnelRemoval = false

    private var acceptance: ExternalAcceptancePresentation { model.acceptancePresentation }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Connection Center").font(.largeTitle.bold())
                localServices
                tunnelClientInstallation
                tunnelConfiguration
                externalAcceptance
                realProjectAcceptance
            }
            .padding(28)
            .frame(maxWidth: 860, alignment: .leading)
        }
        .onAppear {
            tunnelID = model.connection.tunnelID
            if selectedAcceptanceProjectID.isEmpty {
                selectedAcceptanceProjectID = model.projects.first?.projectID ?? ""
            }
        }
        .sheet(isPresented: Binding(
            get: { model.tunnelImportPreview != nil },
            set: { if !$0 { model.tunnelImportPreview = nil } }
        )) {
            if let preview = model.tunnelImportPreview {
                TunnelExecutionAuthorization(
                    preview: preview,
                    cancel: { model.tunnelImportPreview = nil },
                    authorize: { model.authorizeTunnelClientImport() }
                )
            }
        }
        .sheet(isPresented: Binding(
            get: { model.tunnelImportPlan != nil },
            set: { if !$0 { model.tunnelImportPlan = nil } }
        )) {
            if let plan = model.tunnelImportPlan {
                TunnelInstallConfirmation(
                    plan: plan,
                    replacing: model.installedTunnelClient != nil,
                    cancel: { model.tunnelImportPlan = nil },
                    confirm: { model.installSelectedTunnelClient() }
                )
            }
        }
        .sheet(isPresented: Binding(
            get: { model.acceptanceTaskPlan != nil },
            set: { if !$0 { model.acceptanceTaskPlan = nil } }
        )) {
            if let plan = model.acceptanceTaskPlan {
                AcceptanceTaskConfirmation(
                    plan: plan,
                    cancel: { model.acceptanceTaskPlan = nil },
                    confirm: { model.createRealProjectAcceptanceTask() }
                )
            }
        }
        .confirmationDialog(
            "Remove the managed Tunnel Client?",
            isPresented: $confirmTunnelRemoval,
            titleVisibility: .visible
        ) {
            Button("Stop runtime and remove binary", role: .destructive) {
                model.removeInstalledTunnelClient()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Removal is blocked unless tunnel-client confirms the managed runtime is stopped. Your Tunnel ID and Keychain Runtime key are preserved.")
        }
    }

    private var localServices: some View {
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
    }

    private var tunnelClientInstallation: some View {
        GroupBox("Tunnel Client installation") {
            VStack(alignment: .leading, spacing: 12) {
                Link(
                    "Open OpenAI Platform Tunnels",
                    destination: URL(string: "https://platform.openai.com/settings/organization/tunnels")!
                )
                Text("Download the supported macOS Tunnel Client there, then return to Project Brain. The app never downloads or silently upgrades this binary.")
                    .font(.caption).foregroundStyle(.secondary)
                if let installed = model.installedTunnelClient {
                    Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 7) {
                        GridRow { Text("Managed binary"); Text("Installed").foregroundStyle(.green) }
                        GridRow { Text("Version"); Text(installed.version) }
                        GridRow { Text("Architecture"); Text(installed.architecture.rawValue) }
                        GridRow {
                            Text("SHA-256")
                            Text(installed.sha256).font(.caption.monospaced()).textSelection(.enabled)
                        }
                        GridRow { Text("Compatibility manifest"); Text("schema \(installed.manifestSchemaVersion)") }
                    }
                } else {
                    Label("No App-managed Tunnel Client is installed", systemImage: "shippingbox")
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Button(model.installedTunnelClient == nil ? "Select Tunnel Client…" : "Replace / Upgrade…") {
                        chooseTunnelClient()
                    }.buttonStyle(.borderedProminent)
                    if model.installedTunnelClient != nil {
                        Button("Validate again") { model.validateInstalledTunnelClient() }
                        Button("Reveal installed location") { model.revealInstalledTunnelClient() }
                        Button("Remove binary", role: .destructive) { confirmTunnelRemoval = true }
                    }
                }
                Text("Selection performs only static checks: regular non-symlink Mach-O, bounded size, architecture, SHA-256, quarantine, and code-signing status. Project Brain executes fixed `--version` only after a separate authorization, and performs a read-only isolated runtime-contract probe before committing an install.")
                    .font(.caption).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var tunnelConfiguration: some View {
        GroupBox("Secure MCP Tunnel") {
            VStack(alignment: .leading, spacing: 12) {
                LabeledContent("Local MCP endpoint") {
                    Text(TunnelClient.localMCPURL.absoluteString).textSelection(.enabled)
                }
                LabeledContent("Compatible tunnel-client") {
                    Text(model.connection.tunnelClientAvailable ? "Available" : "Not installed")
                        .foregroundStyle(model.connection.tunnelClientAvailable ? .green : .orange)
                }
                Label(
                    model.tunnelTokenConfigured ? "Runtime key stored in Keychain" : "Runtime key not configured",
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
                }
                if let url = model.connection.tunnelUIURL.flatMap(URL.init(string:)) {
                    Link("Open local tunnel status UI", destination: url)
                }
                Text("The Runtime key stays in Keychain and the controlled child environment; it is never written to SQLite, launchd plists, logs, tasks, diagnostics, or argv.")
                    .font(.caption).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var externalAcceptance: some View {
        GroupBox("External Acceptance") {
            VStack(alignment: .leading, spacing: 14) {
                Label(acceptance.title, systemImage: acceptanceSymbol)
                    .font(.headline).foregroundStyle(acceptanceColor)
                Text(acceptance.nextAction)
                AcceptanceSteps(model: model)
                if let current = model.acceptanceStatus?.current {
                    Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                        GridRow { Text("Current run"); Text(current.runID).font(.caption.monospaced()) }
                        GridRow { Text("State"); Text(current.status.title) }
                        GridRow { Text("Expires"); Text(current.expiresAt) }
                    }
                }
                if let probe = model.acceptanceStatus?.lastTransportProbe {
                    Label("Historical unattributed MCP transport probe recorded at \(probe.verifiedAt ?? "unknown")", systemImage: "network.badge.shield.half.filled")
                        .foregroundStyle(acceptance.applicableCurrentTransportProbe ? .blue : .orange)
                    Text(acceptance.applicableCurrentTransportProbe
                        ? "The transport evidence matches the current installation/app/Core/Tunnel/contract set, but external ChatGPT acceptance remains Pending."
                        : "The evidence is historical only and does not match the current binding set.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let prompt = model.acceptancePrompt {
                    Text(prompt)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                        .padding(10)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                }
                HStack {
                    if acceptance.canGenerateChallenge {
                        Button("Generate one-time challenge") { model.generateAcceptanceChallenge() }
                            .buttonStyle(.borderedProminent)
                    }
                    if acceptance.canCopyPrompt {
                        Button("Copy ChatGPT prompt and wait") { model.copyAcceptancePromptAndWait() }
                            .buttonStyle(.borderedProminent)
                    }
                    if acceptance.canCancel {
                        Button("Reset acceptance", role: .destructive) { model.resetAcceptance() }
                    }
                }
                Button("Declare workspace configuration prepared") {
                    model.markWorkspaceConfigured()
                }.disabled(model.connection.workspaceConfigured)
                Text("project_brain_acceptance_probe records only unattributed transport evidence: the same local MCP endpoint can consume the challenge. Without trusted ChatGPT control-plane attestation, external acceptance remains Pending. Challenge plaintext is never persisted or exported.")
                    .font(.caption).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var realProjectAcceptance: some View {
        GroupBox("Optional real-project Draft PR acceptance") {
            VStack(alignment: .leading, spacing: 12) {
                Text("This task stays locked until Core supplies an applicable trusted ChatGPT control-plane attestation. Unattributed local or tunneled transport probes cannot unlock it.")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("Registered project", selection: $selectedAcceptanceProjectID) {
                    Text("Select a project").tag("")
                    ForEach(model.projects.filter { $0.registered && $0.acceptingTasks }) { project in
                        Text(project.name).tag(project.projectID)
                    }
                }
                Button("Preview real-project acceptance task") {
                    model.planRealProjectAcceptance(projectID: selectedAcceptanceProjectID)
                }
                .disabled(
                    selectedAcceptanceProjectID.isEmpty
                        || model.acceptanceStatus?.applicableExternalChatGPTVerification == nil
                )
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var acceptanceColor: Color {
        switch acceptance.state {
        case .blocking: .orange
        case .pending: .blue
        case .passed: .green
        }
    }

    private var acceptanceSymbol: String {
        switch acceptance.state {
        case .blocking: "exclamationmark.triangle.fill"
        case .pending: "clock.arrow.circlepath"
        case .passed: "checkmark.seal.fill"
        }
    }

    private func chooseTunnelClient() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = false
        panel.allowedContentTypes = [.data]
        panel.title = "Select the official OpenAI Tunnel Client binary"
        if panel.runModal() == .OK {
            model.prepareTunnelClientImport(selectedURLs: panel.urls)
        }
    }
}

private struct AcceptanceSteps: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            step("Core helper ready", model.health != nil)
            step("Worker and MCP ready", model.services?.status == "healthy")
            step("Local MCP initialize passed", model.connection.localMCPTransportHealthy)
            step("Compatible Tunnel Client installed", model.connection.tunnelClientAvailable)
            step("Tunnel ID and Runtime key configured", model.connection.tunnelConfigured)
            step("Tunnel process / health / ready", model.connection.tunnelProcessRunning && model.connection.tunnelHealthy && model.connection.tunnelReady)
            step("Workspace operator-declared", model.connection.workspaceConfigured)
            step("One-time challenge generated", model.acceptanceStatus?.current != nil)
            step("Probe prompt copied", model.acceptanceStatus?.current?.status == .waitingForChatGPT || model.acceptanceStatus?.current?.status == .mcpTransportProbePassed)
            step("Unattributed MCP transport probe recorded", model.acceptanceStatus?.lastTransportProbe != nil)
            step("Trusted ChatGPT external attestation", model.acceptanceStatus?.applicableExternalChatGPTVerification != nil)
        }
    }

    private func step(_ title: String, _ passed: Bool) -> some View {
        Label(title, systemImage: passed ? "checkmark.circle.fill" : "circle")
            .foregroundStyle(passed ? .green : .secondary)
            .font(.caption)
    }
}

private struct TunnelExecutionAuthorization: View {
    let preview: TunnelClientImportPreview
    let cancel: () -> Void
    let authorize: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Authorize Tunnel Client execution").font(.title.bold())
            Text("No selected bytes have been executed. Review the static preflight below before authorizing one fixed `--version` command.")
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow { Text("Selected file"); Text(preview.source.lastPathComponent) }
                GridRow { Text("Architecture"); Text(preview.architecture.rawValue) }
                GridRow { Text("Size"); Text(ByteCountFormatter.string(fromByteCount: Int64(preview.fileSize), countStyle: .file)) }
                GridRow { Text("Quarantine"); Text(preview.quarantineStatus) }
                GridRow { Text("Code signing"); Text(preview.signingStatus) }
                GridRow {
                    Text("SHA-256")
                    Text(preview.sha256).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
            Label(preview.sourceAttestation, systemImage: "person.crop.circle.badge.exclamationmark")
                .foregroundStyle(.orange)
            Text("A valid code signature is not an OpenAI identity proof because this build does not pin an official signing requirement or release digest.")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
            HStack {
                Button("Cancel", action: cancel)
                Spacer()
                Button("Authorize fixed --version", action: authorize)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(width: 720, height: 520)
    }
}

private struct TunnelInstallConfirmation: View {
    let plan: TunnelClientValidation
    let replacing: Bool
    let cancel: () -> Void
    let confirm: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(replacing ? "Replace Tunnel Client" : "Install Tunnel Client")
                .font(.title.bold())
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow { Text("Selected file"); Text(plan.source.lastPathComponent) }
                GridRow { Text("Version"); Text(plan.version) }
                GridRow { Text("Architecture"); Text(plan.architecture.rawValue) }
                GridRow { Text("Runtime contract"); Text(String(plan.runtimesContract)) }
                GridRow {
                    Text("SHA-256")
                    Text(plan.sha256).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
            Label(plan.sourceAttestation, systemImage: "person.crop.circle.badge.checkmark")
                .foregroundStyle(.orange)
            Text("Project Brain has validated compatibility and integrity of the selected bytes, but no machine-verifiable official release digest is bundled. Confirm that you selected the file downloaded from OpenAI Platform Tunnels.")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
            HStack {
                Button("Cancel", action: cancel)
                Spacer()
                Button(replacing ? "Confirm replacement" : "Confirm installation", action: confirm)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(width: 680, height: 470)
    }
}

private struct AcceptanceTaskConfirmation: View {
    let plan: AcceptanceTaskPlanResponse
    let cancel: () -> Void
    let confirm: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Preview real-project acceptance task").font(.title.bold())
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow { Text("Project"); Text(plan.projectName) }
                GridRow { Text("Bound acceptance run"); Text(plan.acceptanceRunID).font(.caption.monospaced()) }
                GridRow { Text("Task revision"); Text(String(plan.revision)) }
                GridRow { Text("Only allowed file"); Text(plan.changedFiles.joined(separator: ", ")).font(.caption.monospaced()) }
            }
            Text(plan.effect)
            Label("Uses an isolated worktree, Codex, verification seal, push, and Draft PR. No merge or default-checkout mutation.", systemImage: "checkmark.shield")
                .font(.caption)
            Spacer()
            HStack {
                Button("Cancel", action: cancel)
                Spacer()
                Button("Create acceptance task", action: confirm)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(width: 700, height: 450)
    }
}
