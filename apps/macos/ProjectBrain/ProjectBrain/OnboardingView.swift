import AppKit
import ProjectBrainKit
import SwiftUI

struct OnboardingView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                ForEach(OnboardingStage.allCases, id: \.self) { stage in
                    Capsule()
                        .fill(progressColor(stage))
                        .frame(height: 5)
                }
            }
            .padding(24)

            VStack(alignment: .leading, spacing: 20) {
                Label(model.onboarding.stage.title, systemImage: stageSymbol)
                    .font(.largeTitle.bold())
                stageContent
                Spacer()
                HStack {
                    Button("Back") { model.goBackOnboarding() }
                        .disabled(model.onboarding.stage == .welcome || model.isBusy)
                    Spacer()
                    actionButton
                }
            }
            .padding(36)
        }
        .frame(width: 700, height: 520)
    }

    @ViewBuilder private var stageContent: some View {
        switch model.onboarding.stage {
        case .welcome:
            Text("Project Brain runs locally. It stores project configuration and task history in a private local runtime. Credentials stay in macOS Keychain and are never placed in task data or diagnostic exports.")
                .font(.title3)
            Label("No terminal commands are required", systemImage: "checkmark.shield")
            Label("Project checkouts are not switched or cleaned", systemImage: "folder.badge.gearshape")
        case .runtime:
            Text("The app will install its signed-in-bundle Core helper into Application Support, initialize ~/.project-brain, and validate Git, Codex, and GitHub CLI availability.")
            Text("Existing runtime data is preserved during install, upgrade, and service removal.")
                .foregroundStyle(.secondary)
        case .project:
            Text("Choose the first Git repository Project Brain may manage. The repository, origin, default branch, Codex executable, and managed worktree boundary are validated before any configuration is written.")
            if let selected = model.onboarding.selectedRepository {
                Label(URL(filePath: selected).lastPathComponent, systemImage: "folder.fill")
            }
        case .plan:
            if let plan = model.projectPlan?.plan {
                PlanSummary(plan: plan)
            } else {
                Text("Preparing the validated configuration plan…")
            }
        case .services:
            Text("Install the periodic one-task Worker and loopback-only MCP service. Both launchd definitions use fixed absolute arguments and no shell wrapper.")
            Label("Runtime and task history are preserved on uninstall", systemImage: "externaldrive.badge.checkmark")
        case .health:
            Text("Run local checks for the runtime, database schema, lock, project repository, Git, Codex, GitHub CLI, Worker, and MCP service.")
            if let health = model.health {
                Text("Last result: \(health.status)").font(.headline)
            }
        case .ready:
            Text("Local Project Brain is ready to receive tasks.").font(.title2.bold())
            Label("Secure MCP Tunnel and ChatGPT external acceptance are still pending", systemImage: "hourglass")
                .foregroundStyle(.orange)
            Text("Continue in Connection Center when you are able to run the real external acceptance flow. Local checks do not mark that flow as passed.")
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private var actionButton: some View {
        switch model.onboarding.stage {
        case .welcome:
            Button("Continue") { model.acknowledgeWelcome() }.buttonStyle(.borderedProminent)
        case .runtime:
            Button("Install local runtime") { model.prepareRuntime() }.buttonStyle(.borderedProminent)
        case .project:
            Button("Choose repository…", action: chooseRepository).buttonStyle(.borderedProminent)
        case .plan:
            Button("Confirm and add project") { model.applyNewProject() }
                .buttonStyle(.borderedProminent).disabled(model.projectPlan == nil)
        case .services:
            Button("Install and start services") { model.installOnboardingServices() }
                .buttonStyle(.borderedProminent)
        case .health:
            Button("Run health check") { model.runOnboardingHealthCheck() }
                .buttonStyle(.borderedProminent)
        case .ready:
            Button("Open Project Brain") { model.finishOnboarding() }.buttonStyle(.borderedProminent)
        }
    }

    private var stageSymbol: String {
        switch model.onboarding.stage {
        case .welcome: "brain.head.profile"
        case .runtime: "shippingbox"
        case .project: "folder"
        case .plan: "doc.text.magnifyingglass"
        case .services: "gearshape.2"
        case .health: "stethoscope"
        case .ready: "checkmark.seal"
        }
    }

    private func progressColor(_ stage: OnboardingStage) -> Color {
        let current = OnboardingStage.allCases.firstIndex(of: model.onboarding.stage) ?? 0
        let item = OnboardingStage.allCases.firstIndex(of: stage) ?? 0
        return item <= current ? .accentColor : Color.secondary.opacity(0.2)
    }

    private func chooseRepository() {
        let panel = NSOpenPanel()
        panel.title = "Choose a Git repository"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            model.planNewProject(repository: url)
        }
    }
}

struct PlanSummary: View {
    let plan: ProjectPlan

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 12) {
            row("Project", plan.projectID)
            row("Action", plan.action.capitalized)
            row("Revision", plan.nextRevision.map(String.init) ?? "—")
            row("Config hash", plan.nextSHA256.map { String($0.prefix(12)) } ?? "—")
            row("Changed fields", plan.changedFields.joined(separator: ", "))
            row("Existing active tasks", String(plan.nonterminalTaskCount))
        }
        Text(plan.taskSnapshotEffect).font(.caption).foregroundStyle(.secondary)
    }

    private func row(_ title: String, _ value: String) -> some View {
        GridRow {
            Text(title).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }
}
