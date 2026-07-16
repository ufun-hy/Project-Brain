import AppKit
import Combine
import Foundation
import ProjectBrainKit

enum ProductSection: String, CaseIterable, Identifiable {
    case tasks = "Task Center"
    case projects = "Projects"
    case connection = "Connection Center"
    case diagnostics = "Diagnostics"
    case settings = "Settings"

    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .tasks: "checklist"
        case .projects: "folder"
        case .connection: "point.3.connected.trianglepath.dotted"
        case .diagnostics: "stethoscope"
        case .settings: "gearshape"
        }
    }
}

struct UserFacingIssue: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let message: String
    let nextAction: String
}

private struct ProductSnapshot: Sendable {
    let tasks: [TaskSummary]
    let projects: [ProjectSummary]
    let services: ServiceStatusResponse
    let health: HealthResponse
}

private actor ProductShellBackend {
    private let installer: HelperInstaller
    private var client: CoreClient?

    init(installer: HelperInstaller) { self.installer = installer }

    func prepare(bundledHelper: URL) throws -> ProductSnapshot {
        let result = try installer.install(bundledHelper: bundledHelper) { destination, action in
            guard action == .upgraded || action == .current else { return }
            let candidateClient = try CoreClient(executable: destination)
            let current = try candidateClient.serviceStatus()
            if current.status != "not_installed" {
                _ = try candidateClient.perform(.restart)
            }
        }
        let client = try CoreClient(executable: result.destination)
        _ = try client.initializeRuntime()
        self.client = client
        return try loadSnapshot(client: client)
    }

    func refresh() throws -> ProductSnapshot { try loadSnapshot(client: requireClient()) }
    func task(_ identifier: String) throws -> TaskDetail { try requireClient().task(identifier) }
    func planProject(_ draft: ProjectDraft) throws -> ProjectMutationResponse {
        try requireClient().planProject(draft)
    }
    func addProject(_ draft: ProjectDraft) throws -> ProjectMutationResponse {
        try requireClient().addProject(draft)
    }
    func planProjectUpdate(
        _ identifier: String,
        draft: ProjectUpdateDraft
    ) throws -> ProjectMutationResponse {
        try requireClient().planProjectUpdate(identifier, draft: draft)
    }
    func updateProject(
        _ identifier: String,
        draft: ProjectUpdateDraft
    ) throws -> ProjectMutationResponse {
        try requireClient().updateProject(identifier, draft: draft)
    }
    func planLifecycle(
        projectID: String,
        action: ProjectLifecycleAction
    ) throws -> ProjectLifecyclePlan {
        try requireClient().planProjectLifecycle(projectID, action: action)
    }
    func applyLifecycle(
        projectID: String,
        action: ProjectLifecycleAction
    ) throws -> ProjectLifecycleAppliedResponse {
        try requireClient().applyProjectLifecycle(projectID, action: action)
    }
    func health() throws -> HealthResponse { try requireClient().health() }
    func service(_ action: ServiceAction) throws -> (ActionResponse, ServiceStatusResponse) {
        let client = try requireClient()
        return (try client.perform(action), try client.serviceStatus())
    }

    private func requireClient() throws -> CoreClient {
        guard let client else {
            throw CoreClientError.invalidInstallation("The managed Core helper is not ready.")
        }
        return client
    }

    private func loadSnapshot(client: CoreClient) throws -> ProductSnapshot {
        ProductSnapshot(
            tasks: try client.tasks(),
            projects: try client.projects(),
            services: try client.serviceStatus(),
            health: try client.health()
        )
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var selectedSection: ProductSection = .tasks
    @Published private(set) var tasks: [TaskSummary] = []
    @Published private(set) var projects: [ProjectSummary] = []
    @Published private(set) var services: ServiceStatusResponse?
    @Published private(set) var health: HealthResponse?
    @Published private(set) var selectedTask: TaskDetail?
    @Published private(set) var onboarding: OnboardingProgress
    @Published private(set) var connection: ConnectionSnapshot
    @Published var projectDraft: ProjectDraft?
    @Published var projectPlan: ProjectMutationResponse?
    @Published var updateDraft: ProjectUpdateDraft?
    @Published var updatePlan: ProjectMutationResponse?
    @Published var lifecyclePlan: ProjectLifecyclePlan?
    @Published var lifecycleAction: ProjectLifecycleAction?
    @Published var lifecycleProjectID: String?
    @Published private(set) var isBusy = false
    @Published var issue: UserFacingIssue?

    private let backend: ProductShellBackend
    private let onboardingStore: OnboardingStore
    private let connectionStore: ConnectionStore
    private let keychain: KeychainStore
    private var didBootstrap = false

    init(
        installer: HelperInstaller = HelperInstaller(),
        onboardingStore: OnboardingStore = OnboardingStore(),
        connectionStore: ConnectionStore = ConnectionStore(),
        keychain: KeychainStore = KeychainStore()
    ) {
        self.backend = ProductShellBackend(installer: installer)
        self.onboardingStore = onboardingStore
        self.connectionStore = connectionStore
        self.keychain = keychain
        self.onboarding = onboardingStore.load()
        self.connection = connectionStore.load()
    }

    var menuSnapshot: MenuBarSnapshot {
        MenuBarSnapshot.make(tasks: tasks, service: services)
    }

    var tunnelTokenConfigured: Bool {
        (try? keychain.read(account: "secure-mcp-tunnel-token")) != nil
    }

    func bootstrap() {
        guard !didBootstrap else { return }
        didBootstrap = true
        guard onboarding.completed else { return }
        prepareRuntime(advanceOnboarding: false)
    }

    func acknowledgeWelcome() {
        onboarding.stage = .runtime
        persistOnboarding()
    }

    func prepareRuntime(advanceOnboarding: Bool = true) {
        guard let bundled = Bundle.main.url(forResource: "project-brain", withExtension: nil) else {
            present(CoreClientError.invalidInstallation("The app bundle does not contain Core helper."))
            return
        }
        runOperation {
            try await self.backend.prepare(bundledHelper: bundled)
        } onSuccess: { snapshot in
            self.apply(snapshot)
            if advanceOnboarding {
                self.onboarding.stage = .project
                self.persistOnboarding()
            }
        }
    }

    func planNewProject(repository: URL, verificationFile: URL? = nil) {
        let draft = ProjectDraft(
            repository: repository,
            name: repository.lastPathComponent,
            codexExecutable: ExecutableDiscovery.find("codex"),
            verificationFile: verificationFile
        )
        projectDraft = draft
        runOperation {
            try await self.backend.planProject(draft)
        } onSuccess: { plan in
            self.projectPlan = plan
            if !self.onboarding.completed {
                self.onboarding.selectedRepository = repository.path
                self.onboarding.projectPlanSHA256 = plan.plan.nextSHA256
                self.onboarding.stage = .plan
                self.persistOnboarding()
            }
        }
    }

    func applyNewProject() {
        guard let draft = projectDraft else { return }
        runOperation {
            try await self.backend.addProject(draft)
        } onSuccess: { response in
            if self.onboarding.completed {
                self.projectPlan = nil
                self.projectDraft = nil
            } else {
                self.projectPlan = response
                self.onboarding.stage = .services
                self.persistOnboarding()
            }
            self.refresh()
        }
    }

    func planProjectUpdate(project: ProjectSummary, draft: ProjectUpdateDraft) {
        updateDraft = draft
        runOperation {
            try await self.backend.planProjectUpdate(project.projectID, draft: draft)
        } onSuccess: { self.updatePlan = $0 }
    }

    func applyProjectUpdate(projectID: String) {
        guard let draft = updateDraft else { return }
        runOperation {
            try await self.backend.updateProject(projectID, draft: draft)
        } onSuccess: { _ in
            self.updatePlan = nil
            self.updateDraft = nil
            self.refresh()
        }
    }

    func planLifecycle(projectID: String, action: ProjectLifecycleAction) {
        runOperation {
            try await self.backend.planLifecycle(projectID: projectID, action: action)
        } onSuccess: { plan in
            self.lifecyclePlan = plan
            self.lifecycleAction = action
            self.lifecycleProjectID = projectID
        }
    }

    func applyLifecycle() {
        guard let action = lifecycleAction, let projectID = lifecycleProjectID else { return }
        runOperation {
            try await self.backend.applyLifecycle(projectID: projectID, action: action)
        } onSuccess: { _ in
            self.lifecyclePlan = nil
            self.lifecycleAction = nil
            self.lifecycleProjectID = nil
            self.refresh()
        }
    }

    func installOnboardingServices() {
        performService(.install) {
            self.onboarding.stage = .health
            self.persistOnboarding()
        }
    }

    func runOnboardingHealthCheck() {
        runOperation {
            try await self.backend.health()
        } onSuccess: { response in
            self.health = response
            if response.status == "healthy" {
                self.onboarding.stage = .ready
                self.persistOnboarding()
            } else {
                self.issue = UserFacingIssue(
                    title: "Local checks need attention",
                    message: "One or more local prerequisites are not ready.",
                    nextAction: "Open Diagnostics, resolve failed checks, then retry."
                )
            }
        }
    }

    func finishOnboarding() {
        onboarding.completed = true
        onboarding.lastError = nil
        persistOnboarding()
        refresh()
    }

    func goBackOnboarding() {
        guard let index = OnboardingStage.allCases.firstIndex(of: onboarding.stage), index > 0 else {
            return
        }
        onboarding.stage = OnboardingStage.allCases[index - 1]
        persistOnboarding()
    }

    func refresh() {
        runOperation {
            try await self.backend.refresh()
        } onSuccess: { self.apply($0) }
    }

    func selectTask(_ task: TaskSummary) {
        runOperation {
            try await self.backend.task(task.taskID)
        } onSuccess: { self.selectedTask = $0 }
    }

    func performService(_ action: ServiceAction, completion: (() -> Void)? = nil) {
        runOperation {
            try await self.backend.service(action)
        } onSuccess: { _, status in
            self.services = status
            completion?()
        }
    }

    func saveTunnelToken(_ token: String) {
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        do {
            try keychain.save(token, account: "secure-mcp-tunnel-token")
            connection.tunnelConfigured = true
            connection.externalAcceptance = .readyToTest
            connectionStore.save(connection)
        } catch {
            present(error)
        }
    }

    func removeTunnelToken() {
        do {
            try keychain.remove(account: "secure-mcp-tunnel-token")
            connection.tunnelConfigured = false
            connection.externalAcceptance = .notStarted
            connectionStore.save(connection)
        } catch {
            present(error)
        }
    }

    func markWorkspaceConfigured() {
        connection.workspaceConfigured = true
        if connection.tunnelConfigured {
            connection.externalAcceptance = .readyToTest
        }
        connectionStore.save(connection)
    }

    func restartOnboarding() {
        onboarding = OnboardingProgress()
        persistOnboarding()
    }

    func exportDiagnostics(to url: URL) {
        do {
            let report = DiagnosticReport(
                generatedAt: ISO8601DateFormatter().string(from: Date()),
                appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString")
                    as? String ?? "0.6.0",
                aggregateStatus: menuSnapshot.status,
                taskCounts: menuSnapshot.counts,
                services: services?.services ?? [],
                checks: health?.checks ?? [],
                projects: projects,
                connection: connection
            )
            let data = try report.encoded()
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: url.path
            )
        } catch {
            present(error)
        }
    }

    private func apply(_ snapshot: ProductSnapshot) {
        tasks = snapshot.tasks
        projects = snapshot.projects
        services = snapshot.services
        health = snapshot.health
        connection.localMCPStatus = snapshot.services.services
            .first(where: { $0.name == "mcp" })?.state ?? "unknown"
        connection.lastCheckedAt = ISO8601DateFormatter().string(from: Date())
        connectionStore.save(connection)
    }

    private func persistOnboarding() { onboardingStore.save(onboarding) }

    private func runOperation<Value: Sendable>(
        _ operation: @escaping () async throws -> Value,
        onSuccess: @escaping @MainActor (Value) -> Void
    ) {
        guard !isBusy else { return }
        isBusy = true
        Task {
            do {
                let value = try await operation()
                onSuccess(value)
            } catch {
                present(error)
            }
            isBusy = false
        }
    }

    private func present(_ error: Error) {
        if let core = error as? CoreClientError {
            issue = UserFacingIssue(
                title: core.userTitle,
                message: core.localizedDescription,
                nextAction: core.nextAction
            )
        } else {
            issue = UserFacingIssue(
                title: "Project Brain needs attention",
                message: SecretRedactor.redact(error.localizedDescription),
                nextAction: "Open Diagnostics, review failed checks, then retry."
            )
        }
        onboarding.lastError = issue?.message
        persistOnboarding()
    }
}
