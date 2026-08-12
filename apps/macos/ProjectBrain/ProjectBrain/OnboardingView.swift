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
                if !model.installationStatus.isInstalled {
                    InstallationNotice(
                        status: model.installationStatus,
                        reveal: model.revealApplicationBundle
                    )
                }
                if let issue = model.issue {
                    OnboardingIssueNotice(issue: issue, model: model)
                }
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
        .frame(width: 760, height: 650)
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
                TextField("Project name", text: $model.onboardingProjectName)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("onboarding-project-name")
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
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Run local checks for the runtime, database schema, lock, project repository, Git, Codex, GitHub CLI, Worker, and MCP service.")
                    if let health = model.health {
                        if health.readinessProblems.isEmpty, health.status == "healthy" {
                            Label("All local checks passed", systemImage: "checkmark.circle.fill")
                                .font(.headline)
                                .foregroundStyle(.green)
                        } else {
                            Text(
                                String(
                                    format: String(localized: "Readiness blocker count format"),
                                    health.readinessProblems.count
                                )
                            )
                            .font(.headline)
                            VStack(alignment: .leading, spacing: 10) {
                                ForEach(health.readinessProblems) { problem in
                                    ReadinessProblemNotice(problem: problem)
                                }
                            }
                            .accessibilityIdentifier("readiness-problem-list")
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
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
            if model.onboarding.selectedRepository == nil {
                Button("Choose repository…", action: chooseRepository)
                    .buttonStyle(.borderedProminent)
            } else {
                Button("Review configuration") { model.planSelectedOnboardingProject() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.onboardingProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        case .plan:
            Button(planActionTitle) { model.applyNewProject() }
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

    private var planActionTitle: String {
        switch model.projectPlan?.plan.action {
        case "use_existing": "Confirm and use existing project"
        case "update": "Confirm and update project"
        default: "Confirm and add project"
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
            model.selectOnboardingRepository(url)
        }
    }
}

struct PlanSummary: View {
    let plan: ProjectPlan

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 12) {
            row("Project", plan.nextName ?? plan.currentName ?? plan.projectID)
            row("Action", plan.action == "use_existing" ? "Use existing" : plan.action.capitalized)
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

private struct ReadinessProblemNotice: View {
    let problem: ReadinessProblem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(copy.title, systemImage: copy.symbol)
                .font(.headline)
            Text(copy.message)
            Label(copy.nextAction, systemImage: "arrow.right.circle")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("readiness-problem-\(problem.kind.rawValue)")
    }

    private var copy: (title: String, message: String, nextAction: String, symbol: String) {
        switch problem.kind {
        case .git:
            return (
                String(localized: "Git is not installed"),
                String(localized: "Project Brain could not find the Git executable."),
                String(localized: "Install Apple Command Line Tools or Git, then run the health check again."),
                "arrow.triangle.branch"
            )
        case .codex:
            return (
                String(localized: "Codex CLI is not installed"),
                String(localized: "Project Brain could not find an executable Codex CLI for this project."),
                String(localized: "Install Codex CLI, reopen Project Brain, then run the health check again."),
                "terminal"
            )
        case .githubCLI:
            return (
                String(localized: "GitHub CLI is not installed"),
                String(localized: "Project Brain could not find the GitHub CLI."),
                String(localized: "Install GitHub CLI, sign in to GitHub, then run the health check again."),
                "chevron.left.forwardslash.chevron.right"
            )
        case .githubAuthentication:
            return (
                String(localized: "GitHub sign-in is required"),
                String(localized: "GitHub CLI is installed, but no active GitHub login is available."),
                String(localized: "Sign in to GitHub, then run the health check again."),
                "person.crop.circle.badge.exclamationmark"
            )
        case .runtimeRoot:
            return (
                String(localized: "Local runtime is unavailable"),
                String(localized: "Project Brain could not initialize or access its private runtime."),
                String(localized: "Reinstall the local runtime, then run the health check again."),
                "externaldrive.badge.exclamationmark"
            )
        case .database:
            return (
                String(localized: "Local database is not ready"),
                String(localized: "The Project Brain database schema could not be validated."),
                String(localized: "Reinstall or upgrade the local runtime, then run the health check again."),
                "cylinder.split.1x2"
            )
        case .runtimeLock:
            return (
                String(localized: "Local runtime is busy"),
                String(localized: "Another Project Brain operation currently holds the runtime lock."),
                String(localized: "Wait for the active operation to finish, then run the health check again."),
                "lock.fill"
            )
        case .repository:
            return (
                String(localized: "Project repository is not ready"),
                String(localized: "The selected project folder is unavailable or is not a valid Git repository."),
                String(localized: "Go back and choose a valid Git repository."),
                "folder.badge.questionmark"
            )
        case .origin:
            return (
                String(localized: "Git origin is not configured"),
                String(localized: "The selected repository does not have a usable origin remote."),
                String(localized: "Configure the repository origin, then run the health check again."),
                "network"
            )
        case .defaultBranch:
            return (
                String(localized: "Default branch is not ready"),
                String(localized: "The configured default branch could not be validated."),
                String(localized: "Correct the repository default branch, then run the health check again."),
                "arrow.triangle.branch"
            )
        case .launchdConfiguration:
            return (
                String(localized: "Background-service configuration is unsafe"),
                String(localized: "The project configuration contains a path that background services cannot use safely."),
                String(localized: "Update the project configuration, then reinstall background services."),
                "gearshape.2"
            )
        case .worktree:
            return (
                String(localized: "Managed worktree folder is not ready"),
                String(localized: "Project Brain could not validate its isolated worktree boundary."),
                String(localized: "Correct the worktree configuration, then run the health check again."),
                "square.stack.3d.up"
            )
        case .worker:
            return (
                String(localized: "Worker service is not running"),
                String(localized: "The background Worker is not installed or did not start successfully."),
                String(localized: "Go back and reinstall or start background services."),
                "gearshape.2"
            )
        case .mcpService:
            return (
                String(localized: "MCP service is not running"),
                String(localized: "The local MCP service is not installed or did not start successfully."),
                String(localized: "Go back and reinstall or start background services."),
                "point.3.connected.trianglepath.dotted"
            )
        case .mcpTransport:
            return (
                String(localized: "Local MCP connection failed"),
                String(localized: "Project Brain could not initialize communication with the local MCP service."),
                String(localized: "Restart background services, then run the health check again."),
                "cable.connector"
            )
        case .project:
            return (
                String(localized: "Project configuration is not ready"),
                String(localized: "The registered project could not be validated."),
                String(localized: "Go back and review the project configuration."),
                "folder.badge.gearshape"
            )
        case .other:
            let detail = problem.details.first.map(SecretRedactor.redact)
                ?? String(localized: "No additional detail was provided.")
            return (
                String(localized: "A local readiness check failed"),
                String(
                    format: String(localized: "Readiness check detail format"),
                    detail
                ),
                String(localized: "Review the detail above, correct the problem, then run the health check again."),
                "exclamationmark.triangle.fill"
            )
        }
    }
}

private struct InstallationNotice: View {
    let status: ApplicationInstallationStatus
    let reveal: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(status.title, systemImage: "externaldrive.badge.exclamationmark")
                .font(.headline)
            Text(status.guidance).font(.callout)
            Button("Show current copy in Finder", action: reveal)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("application-installation-notice")
    }
}

private struct OnboardingIssueNotice: View {
    let issue: UserFacingIssue
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(issue.title, systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
            Text(issue.message)
            Text("Next: \(issue.nextAction)").font(.callout).foregroundStyle(.secondary)
            if let conflict = issue.conflict {
                Text("Conflicting project: \(conflict.existingProjectName) (\(conflict.existingProjectID))")
                    .font(.callout.bold())
                HStack {
                    if conflict.recoveryOptions.contains(.useExistingProject) {
                        Button("Use existing project") { model.useExistingProjectFromConflict() }
                    }
                    if conflict.recoveryOptions.contains(.chooseDifferentRepository) {
                        Button("Choose other directory") { model.chooseDifferentOnboardingRepository() }
                    }
                    if conflict.recoveryOptions.contains(.editProjectName) {
                        Button("Modify name") { model.editOnboardingProjectName() }
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("onboarding-inline-error")
    }
}
