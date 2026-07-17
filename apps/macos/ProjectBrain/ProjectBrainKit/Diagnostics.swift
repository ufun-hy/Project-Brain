import Foundation

public enum ExternalAcceptanceStatus: String, Codable, CaseIterable, Sendable {
    case notStarted = "not_started"
    case readyToTest = "ready_to_test"
    case passed
    case failed

    public var title: String {
        switch self {
        case .notStarted: "Pending acceptance"
        case .readyToTest: "Ready to test"
        case .passed: "Passed"
        case .failed: "Failed"
        }
    }
}

public enum WorkspaceConfigurationStatus: String, Codable, Sendable {
    case notDeclared = "not_declared"
    case operatorDeclared = "operator_declared"
}

public enum ExternalVerificationStatus: String, Codable, Sendable {
    case notVerified = "not_verified"
    case passed
    case failed
}

public struct ConnectionSnapshot: Codable, Equatable, Sendable {
    public var localMCPStatus: String
    public var localMCPTransportHealthy: Bool
    public var tunnelID: String
    public var runtimeTokenConfigured: Bool
    public var tunnelClientAvailable: Bool
    public var tunnelProcessRunning: Bool
    public var tunnelHealthy: Bool
    public var tunnelReady: Bool
    public var tunnelRuntimeState: String
    public var tunnelUIURL: String?
    public var workspaceConfiguration: WorkspaceConfigurationStatus
    public private(set) var externalVerification: ExternalVerificationStatus
    public var lastCheckedAt: String?

    public var tunnelConfigured: Bool {
        runtimeTokenConfigured && TunnelClient.isValidTunnelID(tunnelID)
    }

    public var workspaceConfigured: Bool {
        workspaceConfiguration == .operatorDeclared
    }

    public var externalAcceptance: ExternalAcceptanceStatus {
        if externalVerification == .passed { return .passed }
        if externalVerification == .failed { return .failed }
        if tunnelConfigured,
           tunnelClientAvailable,
           localMCPTransportHealthy,
           tunnelProcessRunning,
           tunnelHealthy,
           tunnelReady {
            return .readyToTest
        }
        return .notStarted
    }

    public init(
        localMCPStatus: String = "unknown",
        localMCPTransportHealthy: Bool = false,
        tunnelID: String = "",
        runtimeTokenConfigured: Bool = false,
        tunnelClientAvailable: Bool = false,
        tunnelProcessRunning: Bool = false,
        tunnelHealthy: Bool = false,
        tunnelReady: Bool = false,
        tunnelRuntimeState: String = "not_configured",
        tunnelUIURL: String? = nil,
        workspaceConfiguration: WorkspaceConfigurationStatus = .notDeclared,
        externalVerification: ExternalVerificationStatus = .notVerified,
        lastCheckedAt: String? = nil,
        _ compatibility: Void = ()
    ) {
        self.localMCPStatus = localMCPStatus
        self.localMCPTransportHealthy = localMCPTransportHealthy
        self.tunnelID = tunnelID
        self.runtimeTokenConfigured = runtimeTokenConfigured
        self.tunnelClientAvailable = tunnelClientAvailable
        self.tunnelProcessRunning = tunnelProcessRunning
        self.tunnelHealthy = tunnelHealthy
        self.tunnelReady = tunnelReady
        self.tunnelRuntimeState = tunnelRuntimeState
        self.tunnelUIURL = tunnelUIURL
        self.workspaceConfiguration = workspaceConfiguration
        _ = externalVerification
        self.externalVerification = .notVerified
        self.lastCheckedAt = lastCheckedAt
    }

    public mutating func apply(_ status: TunnelRuntimeStatus) {
        if let tunnelID = status.tunnelID { self.tunnelID = tunnelID }
        tunnelProcessRunning = status.processRunning
        tunnelHealthy = status.healthy
        tunnelReady = status.ready
        tunnelRuntimeState = status.runtimeState
        tunnelUIURL = status.uiURL?.absoluteString
    }

    public mutating func applyExternalAuthority(
        _ acceptance: ExternalAcceptanceStatusResponse?
    ) {
        if acceptance?.applicableExternalChatGPTVerification != nil {
            externalVerification = .passed
        } else if acceptance?.externalChatGPTVerification.status == "failed" {
            externalVerification = .failed
        } else {
            externalVerification = .notVerified
        }
    }

    private enum CodingKeys: String, CodingKey {
        case localMCPStatus, localMCPTransportHealthy, tunnelID, runtimeTokenConfigured
        case tunnelClientAvailable, tunnelProcessRunning, tunnelHealthy, tunnelReady
        case tunnelRuntimeState, tunnelUIURL, workspaceConfiguration, externalVerification
        case lastCheckedAt
        case legacyTunnelConfigured = "tunnelConfigured"
        case legacyWorkspaceConfigured = "workspaceConfigured"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        localMCPStatus = try values.decodeIfPresent(String.self, forKey: .localMCPStatus) ?? "unknown"
        localMCPTransportHealthy = try values.decodeIfPresent(Bool.self, forKey: .localMCPTransportHealthy) ?? false
        tunnelID = try values.decodeIfPresent(String.self, forKey: .tunnelID) ?? ""
        runtimeTokenConfigured = try values.decodeIfPresent(Bool.self, forKey: .runtimeTokenConfigured)
            ?? values.decodeIfPresent(Bool.self, forKey: .legacyTunnelConfigured)
            ?? false
        tunnelClientAvailable = try values.decodeIfPresent(Bool.self, forKey: .tunnelClientAvailable) ?? false
        tunnelProcessRunning = try values.decodeIfPresent(Bool.self, forKey: .tunnelProcessRunning) ?? false
        tunnelHealthy = try values.decodeIfPresent(Bool.self, forKey: .tunnelHealthy) ?? false
        tunnelReady = try values.decodeIfPresent(Bool.self, forKey: .tunnelReady) ?? false
        tunnelRuntimeState = try values.decodeIfPresent(String.self, forKey: .tunnelRuntimeState) ?? "not_configured"
        tunnelUIURL = try values.decodeIfPresent(String.self, forKey: .tunnelUIURL)
        workspaceConfiguration = try values.decodeIfPresent(
            WorkspaceConfigurationStatus.self,
            forKey: .workspaceConfiguration
        ) ?? ((try values.decodeIfPresent(Bool.self, forKey: .legacyWorkspaceConfigured)) == true
            ? .operatorDeclared : .notDeclared)
        // UserDefaults is not authoritative for external acceptance. Core's
        // Core's schema-v8 authority is applied after the helper snapshot loads.
        externalVerification = .notVerified
        lastCheckedAt = try values.decodeIfPresent(String.self, forKey: .lastCheckedAt)
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(localMCPStatus, forKey: .localMCPStatus)
        try values.encode(localMCPTransportHealthy, forKey: .localMCPTransportHealthy)
        try values.encode(tunnelID, forKey: .tunnelID)
        try values.encode(runtimeTokenConfigured, forKey: .runtimeTokenConfigured)
        try values.encode(tunnelClientAvailable, forKey: .tunnelClientAvailable)
        try values.encode(tunnelProcessRunning, forKey: .tunnelProcessRunning)
        try values.encode(tunnelHealthy, forKey: .tunnelHealthy)
        try values.encode(tunnelReady, forKey: .tunnelReady)
        try values.encode(tunnelRuntimeState, forKey: .tunnelRuntimeState)
        try values.encodeIfPresent(tunnelUIURL, forKey: .tunnelUIURL)
        try values.encode(workspaceConfiguration, forKey: .workspaceConfiguration)
        try values.encode(externalVerification, forKey: .externalVerification)
        try values.encodeIfPresent(lastCheckedAt, forKey: .lastCheckedAt)
    }
}

public final class ConnectionStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    public init(defaults: UserDefaults = .standard, key: String = "productShell.connection.v1") {
        self.defaults = defaults
        self.key = key
    }

    public func load() -> ConnectionSnapshot {
        guard let data = defaults.data(forKey: key),
              let value = try? JSONDecoder().decode(ConnectionSnapshot.self, from: data) else {
            return ConnectionSnapshot()
        }
        return value
    }

    public func save(_ snapshot: ConnectionSnapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        defaults.set(data, forKey: key)
    }
}

public enum DiagnosticSeverity: String, Codable, Sendable {
    case info
    case warning
    case error
}

public enum DiagnosticRepairAction: String, Codable, Sendable {
    case none
    case reinstallHelper
    case restartServices
    case openConnectionCenter
}

public struct DiagnosticItem: Identifiable, Equatable, Sendable {
    public let name: String
    public let passed: Bool
    public let detail: String
    public let severity: DiagnosticSeverity
    public let blocksTaskIntake: Bool
    public let repairAction: DiagnosticRepairAction
    public let manualAdvice: String

    public var id: String { name }

    public init(
        name: String,
        passed: Bool,
        detail: String,
        severity: DiagnosticSeverity,
        blocksTaskIntake: Bool,
        repairAction: DiagnosticRepairAction = .none,
        manualAdvice: String
    ) {
        self.name = name
        self.passed = passed
        self.detail = SecretRedactor.redact(detail)
        self.severity = severity
        self.blocksTaskIntake = blocksTaskIntake
        self.repairAction = repairAction
        self.manualAdvice = manualAdvice
    }
}

public struct DiagnosticReport: Codable, Equatable, Sendable {
    public let generatedAt: String
    public let appVersion: String
    public let aggregateStatus: AggregateStatus
    public let taskCounts: [String: Int]
    public let services: [ServiceItem]
    public let checks: [HealthCheck]
    public let projects: [SafeProjectDiagnostic]
    public let connection: SafeConnectionDiagnostic

    public init(
        generatedAt: String,
        appVersion: String,
        aggregateStatus: AggregateStatus,
        taskCounts: [String: Int],
        services: [ServiceItem],
        checks: [HealthCheck],
        projects: [ProjectSummary],
        connection: ConnectionSnapshot,
        tunnelClient: TunnelClientValidation? = nil,
        acceptance: ExternalAcceptanceStatusResponse? = nil
    ) {
        self.generatedAt = generatedAt
        self.appVersion = appVersion
        self.aggregateStatus = aggregateStatus
        self.taskCounts = taskCounts
        self.services = services
        self.checks = checks.map {
            HealthCheck(name: $0.name, status: $0.status, detail: SecretRedactor.redact($0.detail))
        }
        self.projects = projects.map(SafeProjectDiagnostic.init)
        self.connection = SafeConnectionDiagnostic(
            connection,
            tunnelClient: tunnelClient,
            acceptance: acceptance
        )
    }

    public func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}

public struct SafeConnectionDiagnostic: Codable, Equatable, Sendable {
    public let localMCPStatus: String
    public let localMCPTransportHealthy: Bool
    public let tunnelFingerprint: String?
    public let runtimeCredentialConfigured: Bool
    public let tunnelClientAvailable: Bool
    public let tunnelClientVersion: String?
    public let tunnelClientSHA256: String?
    public let tunnelProcessRunning: Bool
    public let tunnelHealthy: Bool
    public let tunnelReady: Bool
    public let tunnelRuntimeState: String
    public let workspaceConfiguration: WorkspaceConfigurationStatus
    public let externalVerification: ExternalVerificationStatus
    public let currentAcceptanceStatus: ExternalAcceptanceRunStatus?
    public let lastExternalPassAt: String?

    public init(
        _ connection: ConnectionSnapshot,
        tunnelClient: TunnelClientValidation?,
        acceptance: ExternalAcceptanceStatusResponse?
    ) {
        localMCPStatus = SecretRedactor.redact(connection.localMCPStatus)
        localMCPTransportHealthy = connection.localMCPTransportHealthy
        tunnelFingerprint = TunnelClient.isValidTunnelID(connection.tunnelID)
            ? TunnelClient.fingerprint(connection.tunnelID)
            : nil
        runtimeCredentialConfigured = connection.runtimeTokenConfigured
        tunnelClientAvailable = connection.tunnelClientAvailable
        tunnelClientVersion = tunnelClient?.version
        tunnelClientSHA256 = tunnelClient?.sha256
        tunnelProcessRunning = connection.tunnelProcessRunning
        tunnelHealthy = connection.tunnelHealthy
        tunnelReady = connection.tunnelReady
        tunnelRuntimeState = SecretRedactor.redact(connection.tunnelRuntimeState)
        workspaceConfiguration = connection.workspaceConfiguration
        externalVerification = connection.externalVerification
        currentAcceptanceStatus = acceptance?.current?.status
        lastExternalPassAt = acceptance?.applicableExternalChatGPTVerification?.verifiedAt
    }
}

public struct SafeProjectDiagnostic: Codable, Equatable, Sendable {
    public let projectID: String
    public let name: String
    public let defaultBranch: String
    public let acceptingTasks: Bool
    public let configRevision: Int?
    public let configHash: String?

    public init(_ project: ProjectSummary) {
        projectID = project.projectID
        name = project.name
        defaultBranch = project.defaultBranch
        acceptingTasks = project.acceptingTasks
        configRevision = project.configRevision
        configHash = project.shortConfigHash
    }
}

public enum SecretRedactor {
    private static let patterns = [
        #"(?i)(authorization:\s*bearer\s+)[^\s]+"#,
        #"(?i)(token|api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]+"#,
        #"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"#,
        #"\bsk-[A-Za-z0-9_-]{16,}\b"#,
        #"(?:/Users|/private|/tmp|/var|/home)/[^\s,;:)\]]+"#,
    ]

    public static func redact(_ value: String) -> String {
        patterns.reduce(value) { current, pattern in
            guard let expression = try? NSRegularExpression(pattern: pattern) else { return current }
            let range = NSRange(current.startIndex..., in: current)
            return expression.stringByReplacingMatches(
                in: current,
                range: range,
                withTemplate: "<redacted>"
            )
        }
    }
}
