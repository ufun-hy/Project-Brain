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
    let conflict: ProjectConflict?

    init(
        title: String,
        message: String,
        nextAction: String,
        conflict: ProjectConflict? = nil
    ) {
        self.title = title
        self.message = message
        self.nextAction = nextAction
        self.conflict = conflict
    }
}

private struct ProductSnapshot: Sendable {
    let tasks: [TaskSummary]
    let projects: [ProjectSummary]
    let services: ServiceStatusResponse
    let health: HealthResponse
    let selectedTask: TaskDetail?
    let acceptance: ExternalAcceptanceStatusResponse
    let tunnelInstallation: TunnelClientValidation?

    var serviceOnline: Bool {
        let states = Dictionary(uniqueKeysWithValues: services.services.map { ($0.name, $0.state) })
        return ["healthy", "running"].contains(states["worker"])
            && states["mcp"] == "running"
    }
}

private actor ProductShellBackend {
    private let installer: HelperInstaller
    private let tunnelInstaller: TunnelClientInstaller?
    private let cliContractURL: URL?
    private var client: CoreClient?
    private var tunnelClient: TunnelClient?

    init(
        installer: HelperInstaller,
        tunnelInstaller: TunnelClientInstaller?,
        cliContractURL: URL?
    ) {
        self.installer = installer
        self.tunnelInstaller = tunnelInstaller
        self.cliContractURL = cliContractURL
        self.tunnelClient = Self.makeTunnelClient()
    }

    func prepare(bundledHelper: URL) throws -> ProductSnapshot {
        guard let cliContractURL else {
            throw CoreClientError.invalidInstallation(
                "The app bundle does not contain the Core CLI contract."
            )
        }
        let contractDocument: CoreCLIContractDocument
        do {
            contractDocument = try CoreCLIContractDocument(contentsOf: cliContractURL)
        } catch {
            throw CoreClientError.invalidInstallation(
                "The bundled Core CLI contract is invalid."
            )
        }
        let result = try installer.install(
            bundledHelper: bundledHelper,
            cliContract: contractDocument
        ) { destination, action in
            guard action == .upgraded || action == .current else { return }
            let candidateClient = try CoreClient(
                executable: destination,
                cliContract: contractDocument.contract
            )
            let current = try candidateClient.serviceStatus()
            if current.status != "not_installed" {
                _ = try candidateClient.perform(.restart)
            }
        }
        let client = try CoreClient(
            executable: result.destination,
            cliContract: contractDocument.contract
        )
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
    func planExistingProject(_ identifier: String) throws -> ProjectMutationResponse {
        try requireClient().planExistingProject(identifier)
    }
    func confirmExistingProject(
        _ identifier: String,
        planToken: String
    ) throws -> ProjectMutationResponse {
        try requireClient().confirmExistingProject(identifier, planToken: planToken)
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

    func stopTunnel(runtimeToken: String?) throws -> TunnelStopResult {
        try requireTunnelClient().stop(runtimeToken: runtimeToken)
    }

    func reconnectTunnel(_ configuration: TunnelConfiguration) throws -> TunnelRuntimeStatus {
        try requireTunnelClient().reconnect(configuration)
    }

    func preflightTunnelClient(_ selectedURLs: [URL]) throws -> TunnelClientImportPreview {
        try requireTunnelInstaller().prepareImport(selectedURLs: selectedURLs)
    }

    func authorizeTunnelClient(_ preview: TunnelClientImportPreview) throws -> TunnelClientValidation {
        try requireTunnelInstaller().authorize(preview)
    }

    func validateInstalledTunnelClient() throws -> TunnelClientValidation? {
        try requireTunnelInstaller().validateInstalled()
    }

    func installTunnelClient(_ plan: TunnelClientValidation) throws -> TunnelClientInstallResult {
        let installer = try requireTunnelInstaller()
        let profiles = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: ".project-brain/tunnel/profiles")
        let result = try installer.install(plan) { destination, _ in
            _ = try TunnelClient(executable: destination, profileDirectory: profiles)
        }
        let client = try TunnelClient(executable: result.destination, profileDirectory: profiles)
        tunnelClient = client
        return result
    }

    func removeManagedTunnelClient(runtimeToken: String?) throws -> TunnelStopResult {
        let stopped = try requireTunnelClient().stop(runtimeToken: runtimeToken)
        try requireTunnelInstaller().removeManagedBinary(confirmedStop: stopped)
        tunnelClient = nil
        return stopped
    }

    func createAcceptanceChallenge(
        appVersion: String,
        tunnelFingerprint: String
    ) throws -> ExternalAcceptanceCreateResponse {
        try requireClient().createAcceptanceChallenge(
            appVersion: appVersion,
            tunnelFingerprint: tunnelFingerprint
        )
    }

    func markAcceptanceWaiting(_ runID: String) throws -> ExternalAcceptanceMutationResponse {
        try requireClient().markAcceptanceWaiting(runID)
    }

    func resetAcceptance(_ runID: String) throws -> ExternalAcceptanceMutationResponse {
        try requireClient().resetAcceptance(runID)
    }

    func planAcceptanceTask(_ projectID: String) throws -> AcceptanceTaskPlanResponse {
        try requireClient().planAcceptanceTask(projectID)
    }

    func createAcceptanceTask(
        _ projectID: String,
        planToken: String
    ) throws -> AcceptanceTaskCreateResponse {
        try requireClient().createAcceptanceTask(projectID, planToken: planToken)
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

    private func requireTunnelInstaller() throws -> TunnelClientInstaller {
        guard let tunnelInstaller else { throw TunnelClientInstallerError.invalidManifest }
        return tunnelInstaller
    }

    private func loadSnapshot(client: CoreClient, selectedTaskID: String?) throws -> ProductSnapshot {
        ProductSnapshot(
            tasks: try client.tasks(),
            projects: try client.projects(),
            services: try client.serviceStatus(),
            health: try client.readiness(),
            selectedTask: try selectedTaskID.map(client.task),
            acceptance: try client.acceptanceStatus(),
            tunnelInstallation: try? tunnelInstaller?.validateInstalled()
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
    @Published private(set) var installationStatus: ApplicationInstallationStatus
    @Published var onboardingProjectName = ""
    @Published private(set) var connection: ConnectionSnapshot
    @Published var projectDraft: ProjectDraft?
    @Published var projectPlan: ProjectMutationResponse?
    @Published var updateDraft: ProjectUpdateDraft?
    @Published var updatePlan: ProjectMutationResponse?
    @Published var lifecyclePlan: ProjectLifecyclePlan?
    @Published var lifecycleAction: ProjectLifecycleAction?
    @Published var lifecycleProjectID: String?
    @Published var tunnelImportPreview: TunnelClientImportPreview?
    @Published var tunnelImportPlan: TunnelClientValidation?
    @Published private(set) var installedTunnelClient: TunnelClientValidation?
    @Published private(set) var acceptanceStatus: ExternalAcceptanceStatusResponse?
    @Published private(set) var acceptanceChallenge: String?
    @Published var acceptanceTaskPlan: AcceptanceTaskPlanResponse?
    @Published private(set) var isBusy = false
    @Published var issue: UserFacingIssue?

    private let backend: ProductShellBackend
    private let onboardingStore: OnboardingStore
    private let connectionStore: ConnectionStore
    private let keychain: KeychainStore
    private let observation: StateObservationLoop<ProductSnapshot>
    private var didBootstrap = false
    private var tunnelStatusTask: Task<Void, Never>?
    private var acceptanceChallengeRunID: String?
    private var onboardingExistingProjectID: String?

    init(
        installer: HelperInstaller = HelperInstaller(),
        tunnelInstaller: TunnelClientInstaller? = nil,
        onboardingStore: OnboardingStore = OnboardingStore(),
        connectionStore: ConnectionStore = ConnectionStore(),
        keychain: KeychainStore = KeychainStore(),
        applicationBundleURL: URL = Bundle.main.bundleURL,
        cliContractURL: URL? = Bundle.main.url(
            forResource: "project-brain-cli-contract",
            withExtension: "json"
        )
    ) {
        let managedTunnelInstaller = tunnelInstaller ?? Self.makeTunnelInstaller()
        self.backend = ProductShellBackend(
            installer: installer,
            tunnelInstaller: managedTunnelInstaller,
            cliContractURL: cliContractURL
        )
        self.onboardingStore = onboardingStore
        self.connectionStore = connectionStore
        self.keychain = keychain
        self.observation = StateObservationLoop()
        self.onboarding = onboardingStore.load()
        self.installationStatus = ApplicationInstallationStatus(bundleURL: applicationBundleURL)
        self.connection = connectionStore.load()
        self.connection.runtimeTokenConfigured =
            (try? keychain.read(account: "secure-mcp-tunnel-token")) != nil
        self.connection.tunnelClientAvailable = TunnelClient.discover() != nil
        self.installedTunnelClient = try? managedTunnelInstaller?.validateInstalled()
        if let selectedRepository = onboarding.selectedRepository {
            self.onboardingProjectName = URL(filePath: selectedRepository).lastPathComponent
        }
    }

    var menuSnapshot: MenuBarSnapshot {
        MenuBarSnapshot.make(tasks: tasks, service: services)
    }

    var tunnelTokenConfigured: Bool {
        (try? keychain.read(account: "secure-mcp-tunnel-token")) != nil
    }

    var acceptancePresentation: ExternalAcceptancePresentation {
        .make(
            connection: connection,
            acceptance: acceptanceStatus,
            appVersion: Self.appVersion,
            challengeAvailable: acceptanceChallenge != nil
        )
    }

    var acceptancePrompt: String? {
        acceptanceChallenge.map {
            "Please use the Project Brain Connector to call "
                + "project_brain_acceptance_probe with challenge: \($0)"
        }
    }

    func bootstrap() {
        guard !didBootstrap else { return }
        didBootstrap = true
        if onboarding.completed {
            prepareRuntime(advanceOnboarding: false)
            return
        }
        guard let stageIndex = OnboardingStage.allCases.firstIndex(of: onboarding.stage),
              let projectIndex = OnboardingStage.allCases.firstIndex(of: .project),
              stageIndex >= projectIndex else { return }
        if onboarding.stage == .plan {
            // Mutation plans are process-local and token-bound. Re-plan against
            // the preserved database instead of restoring a stale confirmation.
            onboarding.stage = .project
            onboarding.projectPlanSHA256 = nil
            persistOnboarding()
        }
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

    func selectOnboardingRepository(_ repository: URL) {
        onboardingProjectName = repository.lastPathComponent
        planNewProject(repository: repository)
    }

    func planSelectedOnboardingProject() {
        guard let selected = onboarding.selectedRepository else { return }
        planNewProject(repository: URL(filePath: selected))
    }

    func planNewProject(repository: URL, verificationFile: URL? = nil) {
        let canonicalRepository = repository.resolvingSymlinksInPath().standardizedFileURL
        let requestedName = onboardingProjectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let draft = ProjectDraft(
            repository: canonicalRepository,
            name: requestedName.isEmpty ? canonicalRepository.lastPathComponent : requestedName,
            codexExecutable: ExecutableDiscovery.find("codex"),
            verificationFile: verificationFile
        )
        issue = nil
        onboardingExistingProjectID = nil
        projectPlan = nil
        projectDraft = draft
        onboarding.selectedRepository = canonicalRepository.path
        onboarding.lastError = nil
        persistOnboarding()
        runOperation {
            try await self.backend.planProject(draft)
        } onSuccess: { plan in
            self.projectPlan = plan
            if !self.onboarding.completed {
                self.onboarding.projectPlanSHA256 = plan.plan.nextSHA256
                self.onboarding.stage = .plan
                self.persistOnboarding()
            }
        }
    }

    func applyNewProject() {
        guard let token = projectPlan?.plan.planToken else { return }
        let draft = projectDraft
        let existingProjectID = onboardingExistingProjectID
        guard draft != nil || existingProjectID != nil else { return }
        runOperation {
            if let existingProjectID {
                return try await self.backend.confirmExistingProject(
                    existingProjectID,
                    planToken: token
                )
            }
            return try await self.backend.addProject(draft!, planToken: token)
        } onSuccess: { response in
            self.issue = nil
            self.onboardingExistingProjectID = nil
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

    func useExistingProjectFromConflict() {
        guard let conflict = issue?.conflict else { return }
        issue = nil
        projectDraft = nil
        projectPlan = nil
        onboardingExistingProjectID = conflict.existingProjectID
        runOperation {
            try await self.backend.planExistingProject(conflict.existingProjectID)
        } onSuccess: { plan in
            self.projectPlan = plan
            self.onboarding.projectPlanSHA256 = plan.plan.nextSHA256
            self.onboarding.stage = .plan
            self.persistOnboarding()
        }
    }

    func chooseDifferentOnboardingRepository() {
        issue = nil
        projectDraft = nil
        projectPlan = nil
        onboardingExistingProjectID = nil
        onboardingProjectName = ""
        onboarding.selectedRepository = nil
        onboarding.projectPlanSHA256 = nil
        onboarding.lastError = nil
        onboarding.stage = .project
        persistOnboarding()
    }

    func editOnboardingProjectName() {
        issue = nil
        projectPlan = nil
        onboardingExistingProjectID = nil
        onboarding.projectPlanSHA256 = nil
        onboarding.lastError = nil
        onboarding.stage = .project
        persistOnboarding()
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
        guard installationStatus.isInstalled else {
            presentInstallationRequirement()
            return
        }
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
        guard installationStatus.isInstalled else {
            presentInstallationRequirement()
            return
        }
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
        issue = nil
        persistOnboarding()
    }

    func revealApplicationBundle() {
        NSWorkspace.shared.activateFileViewerSelecting([installationStatus.bundleURL])
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

    func prepareTunnelClientImport(selectedURLs: [URL]) {
        runOperation {
            try await self.backend.preflightTunnelClient(selectedURLs)
        } onSuccess: { self.tunnelImportPreview = $0 }
    }

    func authorizeTunnelClientImport() {
        guard let preview = tunnelImportPreview else { return }
        tunnelImportPreview = nil
        runOperation {
            try await self.backend.authorizeTunnelClient(preview)
        } onSuccess: { self.tunnelImportPlan = $0 }
    }

    func installSelectedTunnelClient() {
        guard let plan = tunnelImportPlan else { return }
        runOperation {
            try await self.backend.installTunnelClient(plan)
        } onSuccess: { result in
            self.installedTunnelClient = result.validation
            self.tunnelImportPlan = nil
            self.connection.tunnelClientAvailable = true
            self.connectionStore.save(self.connection)
        }
    }

    func validateInstalledTunnelClient() {
        runOperation {
            try await self.backend.validateInstalledTunnelClient()
        } onSuccess: { self.installedTunnelClient = $0 }
    }

    func revealInstalledTunnelClient() {
        guard let installedTunnelClient else { return }
        NSWorkspace.shared.activateFileViewerSelecting([installedTunnelClient.source])
    }

    func removeInstalledTunnelClient() {
        guard installedTunnelClient != nil, !isBusy else { return }
        let token: String?
        do {
            token = try keychain.read(account: "secure-mcp-tunnel-token")
        } catch {
            present(error)
            return
        }
        runOperation {
            try await self.backend.removeManagedTunnelClient(runtimeToken: token)
        } onSuccess: { stopped in
            self.applyTunnelStatus(stopped.status)
            self.installedTunnelClient = nil
            self.connection.tunnelClientAvailable = TunnelClient.discover() != nil
            self.connectionStore.save(self.connection)
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
        } onSuccess: { self.applyTunnelStatus($0.status) }
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
        guard !isBusy else { return }
        let token: String?
        do {
            token = try keychain.read(account: "secure-mcp-tunnel-token")
        } catch {
            present(error)
            return
        }
        isBusy = true
        Task {
            defer { isBusy = false }
            do {
                let result = try await backend.stopTunnel(runtimeToken: token)
                applyTunnelStatus(result.status)
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

    func generateAcceptanceChallenge() {
        guard acceptancePresentation.canGenerateChallenge,
              TunnelClient.isValidTunnelID(connection.tunnelID) else {
            present(TunnelClientError.invalidTunnelID)
            return
        }
        let appVersion = Self.appVersion
        let fingerprint = TunnelClient.fingerprint(connection.tunnelID)
        runOperation {
            try await self.backend.createAcceptanceChallenge(
                appVersion: appVersion,
                tunnelFingerprint: fingerprint
            )
        } onSuccess: { response in
            self.acceptanceChallenge = response.challenge
            self.acceptanceChallengeRunID = response.run.runID
            self.acceptanceStatus = ExternalAcceptanceStatusResponse(
                status: "ok",
                current: response.run,
                lastTransportProbe: self.acceptanceStatus?.lastTransportProbe,
                externalChatGPTVerification: self.acceptanceStatus?.externalChatGPTVerification
                    ?? .init(status: "pending", reasonCode: "trusted_control_plane_attestation_unavailable"),
                applicableExternalChatGPTVerification: self.acceptanceStatus?.applicableExternalChatGPTVerification,
                coreVersion: response.run.coreVersion,
                acceptanceContractVersion: response.run.acceptanceContractVersion,
                installationFingerprint: self.acceptanceStatus?.installationFingerprint
                    ?? response.run.installationFingerprint
            )
            self.applyExternalVerificationAuthority()
        }
    }

    func copyAcceptancePromptAndWait() {
        guard let prompt = acceptancePrompt,
              let runID = acceptanceChallengeRunID else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(prompt, forType: .string)
        runOperation {
            try await self.backend.markAcceptanceWaiting(runID)
        } onSuccess: { response in
            self.acceptanceStatus = ExternalAcceptanceStatusResponse(
                status: "ok",
                current: response.run,
                lastTransportProbe: self.acceptanceStatus?.lastTransportProbe,
                externalChatGPTVerification: self.acceptanceStatus?.externalChatGPTVerification
                    ?? .init(status: "pending", reasonCode: "trusted_control_plane_attestation_unavailable"),
                applicableExternalChatGPTVerification: self.acceptanceStatus?.applicableExternalChatGPTVerification,
                coreVersion: response.run.coreVersion,
                acceptanceContractVersion: response.run.acceptanceContractVersion,
                installationFingerprint: self.acceptanceStatus?.installationFingerprint
                    ?? response.run.installationFingerprint
            )
        }
    }

    func resetAcceptance() {
        guard let runID = acceptanceStatus?.current?.runID else { return }
        runOperation {
            try await self.backend.resetAcceptance(runID)
        } onSuccess: { response in
            self.acceptanceChallenge = nil
            self.acceptanceChallengeRunID = nil
            self.acceptanceStatus = ExternalAcceptanceStatusResponse(
                status: "ok",
                current: response.run,
                lastTransportProbe: self.acceptanceStatus?.lastTransportProbe,
                externalChatGPTVerification: self.acceptanceStatus?.externalChatGPTVerification
                    ?? .init(status: "pending", reasonCode: "trusted_control_plane_attestation_unavailable"),
                applicableExternalChatGPTVerification: self.acceptanceStatus?.applicableExternalChatGPTVerification,
                coreVersion: response.run.coreVersion,
                acceptanceContractVersion: response.run.acceptanceContractVersion,
                installationFingerprint: self.acceptanceStatus?.installationFingerprint
                    ?? response.run.installationFingerprint
            )
            self.applyExternalVerificationAuthority()
        }
    }

    func planRealProjectAcceptance(projectID: String) {
        runOperation {
            try await self.backend.planAcceptanceTask(projectID)
        } onSuccess: { self.acceptanceTaskPlan = $0 }
    }

    func createRealProjectAcceptanceTask() {
        guard let plan = acceptanceTaskPlan else { return }
        runOperation {
            try await self.backend.createAcceptanceTask(
                plan.projectID,
                planToken: plan.planToken
            )
        } onSuccess: { response in
            self.acceptanceTaskPlan = nil
            if !self.tasks.contains(where: { $0.taskID == response.task.taskID }) {
                self.tasks.insert(response.task, at: 0)
            }
            self.selectedSection = .tasks
        }
    }

    func restartOnboarding() {
        Task { await observation.cancel() }
        onboarding = OnboardingProgress()
        onboardingProjectName = ""
        onboardingExistingProjectID = nil
        projectDraft = nil
        projectPlan = nil
        issue = nil
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

    func quitApplication() {
        shutdown()
        NSApplication.shared.terminate(nil)
    }

    func exportDiagnostics(to url: URL) {
        do {
            let report = DiagnosticReport(
                generatedAt: ISO8601DateFormatter().string(from: Date()),
                appVersion: Self.appVersion,
                aggregateStatus: menuSnapshot.status,
                taskCounts: menuSnapshot.counts,
                services: services?.services ?? [],
                checks: health?.checks ?? [],
                projects: projects,
                connection: connection,
                tunnelClient: installedTunnelClient,
                acceptance: acceptanceStatus
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
        acceptanceStatus = snapshot.acceptance
        installedTunnelClient = snapshot.tunnelInstallation
        if snapshot.selectedTask != nil { selectedTask = snapshot.selectedTask }
        connection.localMCPStatus = snapshot.services.services
            .first(where: { $0.name == "mcp" })?.state ?? "unknown"
        connection.localMCPTransportHealthy = snapshot.health.checks
            .first(where: { $0.name == "mcp_transport" })?.passed == true
        connection.tunnelClientAvailable = TunnelClient.discover() != nil
        connection.lastCheckedAt = ISO8601DateFormatter().string(from: Date())
        let challengeIsActive = snapshot.acceptance.current.map {
            [ExternalAcceptanceRunStatus.challengeReady, .waitingForChatGPT].contains($0.status)
        } ?? false
        if acceptanceChallengeRunID != snapshot.acceptance.current?.runID || !challengeIsActive {
            acceptanceChallenge = nil
            acceptanceChallengeRunID = nil
        }
        applyExternalVerificationAuthority()
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

    private func applyExternalVerificationAuthority() {
        connection.applyExternalAuthority(acceptanceStatus)
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

    private static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString")
            as? String ?? "0.7.0"
    }

    private static func makeTunnelInstaller() -> TunnelClientInstaller? {
        #if SWIFT_PACKAGE
        let bundle = Bundle.module
        #else
        let bundle = Bundle.main
        #endif
        guard let url = bundle.url(
            forResource: "tunnel-client-compatibility",
            withExtension: "json"
        ), let manifest = try? TunnelCompatibilityManifest.load(from: url) else {
            return nil
        }
        return try? TunnelClientInstaller(manifest: manifest)
    }

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
            let conflict: ProjectConflict?
            if case .projectConflict(_, let value) = core {
                conflict = value
            } else {
                conflict = nil
            }
            issue = UserFacingIssue(
                title: core.userTitle,
                message: core.localizedDescription,
                nextAction: core.nextAction,
                conflict: conflict
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

    private func presentInstallationRequirement() {
        issue = UserFacingIssue(
            title: installationStatus.title,
            message: installationStatus.guidance,
            nextAction: "Open the installed copy from /Applications and rerun local health."
        )
        onboarding.lastError = issue?.message
        persistOnboarding()
    }
}
