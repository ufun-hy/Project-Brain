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
    let selectedTask: TaskDetail?

    var serviceOnline: Bool {
        let states = Dictionary(uniqueKeysWithValues: services.services.map { ($0.name, $0.state) })
        return ["healthy", "running"].contains(states["worker"])
            && states["mcp"] == "running"
    }
}

private actor ProductShellBackend {
    private let installer: HelperInstaller
    private var client: CoreClient?
    private var tunnelClient: TunnelClient?

    init(installer: HelperInstaller) {
        self.installer = installer
        self.tunnelClient = Self.makeTunnelClient()
    }

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
        return try loadSnapshot(client: client, selectedTaskID: nil)
    }

    func refresh(selectedTaskID: String?) throws -> ProductSnapshot {
        try loadSnapshot(client: requireClient(), selectedTaskID: selectedTaskID)
    }
    func task(_ identifier: String) throws -> TaskDetail { try requireClient().task(identifier) }
    func planProject(_ draft: ProjectDraft) throws -> ProjectMutationResponse {
        try requireClient().planProject(draft)
    }
    func addProject(_ draft: ProjectDraft, planToken: String) throws -> ProjectMutationResponse {
        try requireClient().addProject(draft, planToken: planToken)
    }
    func planProjectUpdate(
        _ identifier: String,
        draft: ProjectUpdateDraft
    ) throws -> ProjectMutationResponse {
        try requireClient().planProjectUpdate(identifier, draft: draft)
    }
    func updateProject(
        _ identifier: String,
        draft: ProjectUpdateDraft,
        planToken: String
    ) throws -> ProjectMutationResponse {
        try requireClient().updateProject(identifier, draft: draft, planToken: planToken)
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
    func readiness() throws -> HealthResponse { try requireClient().readiness() }
    func service(_ action: ServiceAction) throws -> (ActionResponse, ServiceStatusResponse) {
        let client = try requireClient()
        return (try client.perform(action), try client.serviceStatus())
    }

    func tunnelAvailable() -> Bool {
        if tunnelClient == nil { tunnelClient = Self.makeTunnelClient() }
        return tunnelClient != nil
    }

    func connectTunnel(_ configuration: TunnelConfiguration) throws -> TunnelRuntimeStatus {
        try requireTunnelClient().connect(configuration)
    }

    func tunnelStatus(runtimeToken: String?) throws -> TunnelRuntimeStatus {
        try requireTunnelClient().status(runtimeToken: runtimeToken)
    }

    func stopTunnel(runtimeToken: String?) throws -> TunnelRuntimeStatus {
        try requireTunnelClient().stop(runtimeToken: runtimeToken)
    }

    func reconnectTunnel(_ configuration: TunnelConfiguration) throws -> TunnelRuntimeStatus {
        try requireTunnelClient().reconnect(configuration)
    }

    private func requireClient() throws -> CoreClient {
        guard let client else {
            throw CoreClientError.invalidInstallation("The managed Core helper is not ready.")
        }
        return client
    }

    private func requireTunnelClient() throws -> TunnelClient {
        if tunnelClient == nil { tunnelClient = Self.makeTunnelClient() }
        guard let tunnelClient else { throw TunnelClientError.unavailable }
        return tunnelClient
    }

    private func loadSnapshot(client: CoreClient, selectedTaskID: String?) throws -> ProductSnapshot {
        ProductSnapshot(
            tasks: try client.tasks(),
            projects: try client.projects(),
            services: try client.serviceStatus(),
            health: try client.readiness(),
            selectedTask: try selectedTaskID.map(client.task)
        )
    }

    private static func makeTunnelClient() -> TunnelClient? {
        guard let executable = TunnelClient.discover() else { return nil }
        let profiles = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: ".project-brain/tunnel/profiles")
        return try? TunnelClient(executable: executable, profileDirectory: profiles)
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
    private let observation: StateObservationLoop<ProductSnapshot>
    private var didBootstrap = false
    private var tunnelStatusTask: Task<Void, Never>?

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
        self.observation = StateObservationLoop()
        self.onboarding = onboardingStore.load()
        self.connection = connectionStore.load()
        self.connection.runtimeTokenConfigured =
            (try? keychain.read(account: "secure-mcp-tunnel-token")) != nil
        self.connection.tunnelClientAvailable = TunnelClient.discover() != nil
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
            if self.onboarding.completed { self.startObservation() }
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
        guard let draft = projectDraft, let token = projectPlan?.plan.planToken else { return }
        runOperation {
            try await self.backend.addProject(draft, planToken: token)
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
        guard let draft = updateDraft, let token = updatePlan?.plan.planToken else { return }
        runOperation {
            try await self.backend.updateProject(projectID, draft: draft, planToken: token)
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
            try await self.backend.readiness()
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
        startObservation()
    }

    func goBackOnboarding() {
        guard let index = OnboardingStage.allCases.firstIndex(of: onboarding.stage), index > 0 else {
            return
        }
        onboarding.stage = OnboardingStage.allCases[index - 1]
        persistOnboarding()
    }

    func refresh() {
        let taskID = selectedTask?.taskID
        runOperation {
            try await self.backend.refresh(selectedTaskID: taskID)
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

    func saveAndStartTunnel(tunnelID: String, token: String) {
        let configuration = TunnelConfiguration(tunnelID: tunnelID, runtimeToken: token)
        guard TunnelClient.isValidTunnelID(tunnelID) else {
            present(TunnelClientError.invalidTunnelID)
            return
        }
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            present(TunnelClientError.missingToken)
            return
        }
        do {
            try keychain.save(token, account: "secure-mcp-tunnel-token")
            connection.tunnelID = tunnelID
            connection.runtimeTokenConfigured = true
            connectionStore.save(connection)
        } catch {
            present(error)
            return
        }
        runOperation {
            try await self.backend.connectTunnel(configuration)
        } onSuccess: { self.applyTunnelStatus($0) }
    }

    func startTunnel() {
        do {
            let configuration = try tunnelConfiguration()
            runOperation {
                try await self.backend.connectTunnel(configuration)
            } onSuccess: { self.applyTunnelStatus($0) }
        } catch { present(error) }
    }

    func stopTunnel() {
        let token = try? keychain.read(account: "secure-mcp-tunnel-token")
        runOperation {
            try await self.backend.stopTunnel(runtimeToken: token ?? nil)
        } onSuccess: { self.applyTunnelStatus($0) }
    }

    func reconnectTunnel() {
        do {
            let configuration = try tunnelConfiguration()
            runOperation {
                try await self.backend.reconnectTunnel(configuration)
            } onSuccess: { self.applyTunnelStatus($0) }
        } catch { present(error) }
    }

    func checkTunnelStatus() { refreshTunnelStatus(silent: false) }

    func removeTunnelConfiguration() {
        let token = try? keychain.read(account: "secure-mcp-tunnel-token")
        Task {
            _ = try? await backend.stopTunnel(runtimeToken: token ?? nil)
            do {
                try keychain.remove(account: "secure-mcp-tunnel-token")
                connection.runtimeTokenConfigured = false
                connection.tunnelProcessRunning = false
                connection.tunnelHealthy = false
                connection.tunnelReady = false
                connection.tunnelRuntimeState = "not_configured"
                connectionStore.save(connection)
            } catch { present(error) }
        }
    }

    func markWorkspaceConfigured() {
        connection.workspaceConfiguration = .operatorDeclared
        connectionStore.save(connection)
    }

    func restartOnboarding() {
        Task { await observation.cancel() }
        onboarding = OnboardingProgress()
        persistOnboarding()
    }

    func setApplicationActive(_ active: Bool) {
        Task { await observation.setForeground(active) }
        if active, onboarding.completed { refreshSilently() }
    }

    func shutdown() {
        tunnelStatusTask?.cancel()
        Task { await observation.cancel() }
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
        if snapshot.selectedTask != nil { selectedTask = snapshot.selectedTask }
        connection.localMCPStatus = snapshot.services.services
            .first(where: { $0.name == "mcp" })?.state ?? "unknown"
        connection.localMCPTransportHealthy = snapshot.health.checks
            .first(where: { $0.name == "mcp_transport" })?.passed == true
        connection.tunnelClientAvailable = TunnelClient.discover() != nil
        connection.lastCheckedAt = ISO8601DateFormatter().string(from: Date())
        connectionStore.save(connection)
        refreshTunnelStatus(silent: true)
    }

    private func startObservation() {
        let backend = backend
        Task {
            await observation.start(
                selection: { [weak self] in await self?.selectedTaskIdentifier() },
                refresh: { identifier in
                    let snapshot = try await backend.refresh(selectedTaskID: identifier)
                    return ObservationUpdate(
                        value: snapshot,
                        serviceOnline: snapshot.serviceOnline
                    )
                },
                consume: { [weak self] snapshot in self?.apply(snapshot) }
            )
        }
    }

    private func selectedTaskIdentifier() -> String? { selectedTask?.taskID }

    private func refreshSilently() {
        let identifier = selectedTask?.taskID
        Task {
            do { apply(try await backend.refresh(selectedTaskID: identifier)) }
            catch { /* observation loop applies bounded backoff */ }
        }
    }

    private func refreshTunnelStatus(silent: Bool) {
        guard connection.tunnelClientAvailable,
              !connection.tunnelID.isEmpty,
              tunnelStatusTask == nil else { return }
        let token = try? keychain.read(account: "secure-mcp-tunnel-token")
        tunnelStatusTask = Task {
            defer { tunnelStatusTask = nil }
            do {
                applyTunnelStatus(try await backend.tunnelStatus(runtimeToken: token ?? nil))
            } catch {
                connection.tunnelProcessRunning = false
                connection.tunnelHealthy = false
                connection.tunnelReady = false
                connection.tunnelRuntimeState = "unavailable"
                connectionStore.save(connection)
                if !silent { present(error) }
            }
        }
    }

    private func applyTunnelStatus(_ status: TunnelRuntimeStatus) {
        connection.apply(status)
        connection.lastCheckedAt = ISO8601DateFormatter().string(from: Date())
        connectionStore.save(connection)
    }

    private func tunnelConfiguration() throws -> TunnelConfiguration {
        guard let token = try keychain.read(account: "secure-mcp-tunnel-token") else {
            throw TunnelClientError.missingToken
        }
        guard TunnelClient.isValidTunnelID(connection.tunnelID) else {
            throw TunnelClientError.invalidTunnelID
        }
        return TunnelConfiguration(tunnelID: connection.tunnelID, runtimeToken: token)
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
