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

public struct ConnectionSnapshot: Codable, Equatable, Sendable {
    public var localMCPStatus: String
    public var tunnelConfigured: Bool
    public var workspaceConfigured: Bool
    public var lastCheckedAt: String?
    public var externalAcceptance: ExternalAcceptanceStatus

    public init(
        localMCPStatus: String = "unknown",
        tunnelConfigured: Bool = false,
        workspaceConfigured: Bool = false,
        lastCheckedAt: String? = nil,
        externalAcceptance: ExternalAcceptanceStatus = .notStarted
    ) {
        self.localMCPStatus = localMCPStatus
        self.tunnelConfigured = tunnelConfigured
        self.workspaceConfigured = workspaceConfigured
        self.lastCheckedAt = lastCheckedAt
        self.externalAcceptance = externalAcceptance
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
    public let connection: ConnectionSnapshot

    public init(
        generatedAt: String,
        appVersion: String,
        aggregateStatus: AggregateStatus,
        taskCounts: [String: Int],
        services: [ServiceItem],
        checks: [HealthCheck],
        projects: [ProjectSummary],
        connection: ConnectionSnapshot
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
        self.connection = connection
    }

    public func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
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
