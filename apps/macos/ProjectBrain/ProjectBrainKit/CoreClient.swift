import Foundation

public struct CoreProcessResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: Data
    public let stderr: Data

    public init(exitCode: Int32, stdout: Data, stderr: Data) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public protocol CoreProcessRunning: Sendable {
    func run(
        executable: URL,
        arguments: [String],
        standardInput: Data?
    ) throws -> CoreProcessResult
}

public extension CoreProcessRunning {
    func run(executable: URL, arguments: [String]) throws -> CoreProcessResult {
        try run(executable: executable, arguments: arguments, standardInput: nil)
    }
}

public struct FoundationCoreProcessRunner: CoreProcessRunning {
    public init() {}

    public func run(
        executable: URL,
        arguments: [String],
        standardInput: Data?
    ) throws -> CoreProcessResult {
        let process = Process()
        let output = Pipe()
        let error = Pipe()
        let input = standardInput.map { _ in Pipe() }
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = output
        process.standardError = error
        process.standardInput = input
        try process.run()
        if let standardInput, let input {
            input.fileHandleForWriting.write(standardInput)
            try? input.fileHandleForWriting.close()
        }

        // Draining both handles concurrently avoids a child blocking on a full pipe.
        let group = DispatchGroup()
        let lock = NSLock()
        var stdout = Data()
        var stderr = Data()
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            let data = output.fileHandleForReading.readDataToEndOfFile()
            lock.withLock { stdout = data }
            group.leave()
        }
        group.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            let data = error.fileHandleForReading.readDataToEndOfFile()
            lock.withLock { stderr = data }
            group.leave()
        }
        process.waitUntilExit()
        group.wait()
        return CoreProcessResult(
            exitCode: process.terminationStatus,
            stdout: stdout,
            stderr: stderr
        )
    }
}

public enum CoreClientError: LocalizedError, Equatable, Sendable {
    case invalidInstallation(String)
    case process(String)
    case invalidResponse(String)
    case core(category: String, message: String)
    case projectConflict(message: String, conflict: ProjectConflict)

    public var errorDescription: String? {
        switch self {
        case .invalidInstallation(let message), .process(let message), .invalidResponse(let message):
            message
        case .core(_, let message):
            message
        case .projectConflict(let message, _):
            message
        }
    }

    public var userTitle: String {
        switch self {
        case .invalidInstallation: "Core helper needs repair"
        case .process: "Project Brain could not start"
        case .invalidResponse: "Project Brain returned an invalid response"
        case .core(let category, _):
            switch category {
            case "configuration": "Project configuration needs attention"
            case "service": "Background service needs attention"
            case "security": "A safety check blocked this action"
            case "state_conflict": "Project Brain state changed"
            case "invalid_task": "Review the task details"
            default: "Project Brain needs attention"
            }
        case .projectConflict: "Project registration conflicts with existing data"
        }
    }

    public var nextAction: String {
        switch self {
        case .invalidInstallation: "Reinstall the bundled helper from Settings."
        case .process: "Open Diagnostics and check the helper and runtime."
        case .invalidResponse: "Export diagnostics, then restart the app."
        case .core(let category, _):
            switch category {
            case "configuration": "Review the project plan and update invalid fields."
            case "service": "Use Connection Center to reinstall or restart services."
            case "security": "Choose a validated repository or trusted executable."
            case "state_conflict": "Refresh and review the latest state before retrying."
            case "invalid_task": "Correct the highlighted fields, then review a new plan."
            default: "Open Diagnostics for a safe, detailed check."
            }
        case .projectConflict:
            "Use the existing project, choose another repository, or edit the project name."
        }
    }
}

private struct CoreErrorEnvelope: Decodable {
    let status: String?
    let errorCategory: String?
    let error: String?
    let conflict: ProjectConflict?

    enum CodingKeys: String, CodingKey {
        case status, error, conflict
        case errorCategory = "error_category"
    }
}

public final class CoreClient: @unchecked Sendable {
    public let executable: URL
    public let runtimeRoot: URL
    public let cliContract: CoreCLIContract
    private let runner: any CoreProcessRunning
    private let decoder: JSONDecoder

    public init(
        executable: URL,
        runtimeRoot: URL = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: ".project-brain"),
        cliContract: CoreCLIContract,
        runner: any CoreProcessRunning = FoundationCoreProcessRunner()
    ) throws {
        guard executable.path.hasPrefix("/"), !executable.hasDirectoryPath else {
            throw CoreClientError.invalidInstallation(
                "The managed Core helper must be an absolute executable file."
            )
        }
        guard runtimeRoot.path.hasPrefix("/") else {
            throw CoreClientError.invalidInstallation("The runtime root must be absolute.")
        }
        self.executable = executable.standardizedFileURL
        self.runtimeRoot = runtimeRoot.standardizedFileURL
        self.cliContract = cliContract
        self.runner = runner
        self.decoder = JSONDecoder()
    }

    public func execute<T: Decodable>(_ command: CoreCommand, as type: T.Type = T.self) throws -> T {
        let arguments = command.arguments(runtimeRoot: runtimeRoot, cliContract: cliContract)
        let standardInput: Data?
        do {
            standardInput = try command.standardInput()
        } catch {
            throw CoreClientError.invalidResponse("The local task request could not be encoded.")
        }
        let result: CoreProcessResult
        do {
            result = try runner.run(
                executable: executable,
                arguments: arguments,
                standardInput: standardInput
            )
        } catch let error as CoreClientError {
            throw error
        } catch {
            throw CoreClientError.process(SecretRedactor.redact(error.localizedDescription))
        }
        guard command.acceptedExitCodes.contains(result.exitCode) else {
            let bounded = Data(result.stderr.prefix(8_192))
            if let envelope = try? decoder.decode(CoreErrorEnvelope.self, from: bounded) {
                let message = SecretRedactor.redact(
                    envelope.error ?? "Core operation failed."
                )
                if let conflict = envelope.conflict {
                    throw CoreClientError.projectConflict(
                        message: message,
                        conflict: conflict
                    )
                }
                throw CoreClientError.core(
                    category: envelope.errorCategory ?? "core",
                    message: message
                )
            }
            let detail = String(decoding: bounded, as: UTF8.self)
            throw CoreClientError.process(
                SecretRedactor.redact(detail.isEmpty ? "Core operation failed." : detail)
            )
        }
        let bounded = Data(result.stdout.prefix(512 * 1_024))
        guard !bounded.isEmpty else {
            throw CoreClientError.invalidResponse("Core returned no JSON document.")
        }
        do {
            return try decoder.decode(type, from: bounded)
        } catch {
            throw CoreClientError.invalidResponse("Core returned JSON that this app cannot read.")
        }
    }

    public func initializeRuntime() throws -> RuntimeInitResponse {
        try execute(.initialize)
    }

    public func status() throws -> CoreStatusResponse { try execute(.status) }
    public func tasks() throws -> [TaskSummary] { try execute(.tasks) }
    public func task(_ identifier: String) throws -> TaskDetail { try execute(.task(identifier)) }
    public func projects() throws -> [ProjectSummary] { try execute(.projects) }
    public func health() throws -> HealthResponse { try execute(.health) }
    public func readiness() throws -> HealthResponse { try execute(.readiness) }
    public func serviceStatus() throws -> ServiceStatusResponse { try execute(.serviceStatus) }
    public func perform(_ action: ServiceAction) throws -> ActionResponse {
        try execute(.service(action))
    }
    public func planProject(_ draft: ProjectDraft) throws -> ProjectMutationResponse {
        try execute(.addProject(draft, planToken: nil))
    }
    public func addProject(
        _ draft: ProjectDraft,
        planToken: String
    ) throws -> ProjectMutationResponse {
        try execute(.addProject(draft, planToken: planToken))
    }
    public func planExistingProject(_ identifier: String) throws -> ProjectMutationResponse {
        try execute(.useProject(identifier, planToken: nil))
    }
    public func confirmExistingProject(
        _ identifier: String,
        planToken: String
    ) throws -> ProjectMutationResponse {
        try execute(.useProject(identifier, planToken: planToken))
    }
    public func planProjectUpdate(
        _ identifier: String,
        draft: ProjectUpdateDraft
    ) throws -> ProjectMutationResponse {
        try execute(.updateProject(identifier, draft, planToken: nil))
    }
    public func updateProject(
        _ identifier: String,
        draft: ProjectUpdateDraft,
        planToken: String
    ) throws -> ProjectMutationResponse {
        try execute(.updateProject(identifier, draft, planToken: planToken))
    }
    public func planProjectLifecycle(
        _ identifier: String,
        action: ProjectLifecycleAction
    ) throws -> ProjectLifecyclePlan {
        try execute(.projectLifecycle(identifier, action, execute: false))
    }
    public func applyProjectLifecycle(
        _ identifier: String,
        action: ProjectLifecycleAction
    ) throws -> ProjectLifecycleAppliedResponse {
        try execute(.projectLifecycle(identifier, action, execute: true))
    }
    public func acceptanceStatus() throws -> ExternalAcceptanceStatusResponse {
        try execute(.acceptanceStatus)
    }
    public func createAcceptanceChallenge(
        appVersion: String,
        tunnelFingerprint: String
    ) throws -> ExternalAcceptanceCreateResponse {
        try execute(.acceptanceCreate(
            appVersion: appVersion,
            tunnelFingerprint: tunnelFingerprint
        ))
    }
    public func markAcceptanceWaiting(_ runID: String) throws -> ExternalAcceptanceMutationResponse {
        try execute(.acceptanceWaiting(runID))
    }
    public func resetAcceptance(_ runID: String) throws -> ExternalAcceptanceMutationResponse {
        try execute(.acceptanceReset(runID))
    }
    public func planAcceptanceTask(_ projectID: String) throws -> AcceptanceTaskPlanResponse {
        try execute(.acceptanceTaskPlan(projectID))
    }
    public func createAcceptanceTask(
        _ projectID: String,
        planToken: String
    ) throws -> AcceptanceTaskCreateResponse {
        try execute(.acceptanceTaskCreate(projectID, planToken: planToken))
    }
    public func planLocalTask(_ request: LocalTaskRequest) throws -> LocalTaskPlanResponse {
        try execute(.localTaskPlan(request))
    }
    public func createLocalTask(
        _ request: LocalTaskRequest,
        planToken: String
    ) throws -> LocalTaskCreateResponse {
        try execute(.localTaskCreate(request, planToken: planToken))
    }
}
