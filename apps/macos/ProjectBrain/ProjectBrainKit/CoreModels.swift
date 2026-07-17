import Foundation

public enum TaskStatus: String, Codable, CaseIterable, Sendable {
    case pending
    case running
    case recoveryBlocked = "recovery_blocked"
    case verificationFailed = "verification_failed"
    case retryPending = "retry_pending"
    case needsChanges = "needs_changes"
    case awaitingReview = "awaiting_review"
    case readyToMerge = "ready_to_merge"
    case merging
    case accepted
    case mergeFailed = "merge_failed"
    case failed
    case superseded
    case expired

    public var title: String {
        switch self {
        case .pending: "Pending"
        case .running: "Running"
        case .recoveryBlocked: "Recovery blocked"
        case .verificationFailed: "Verification failed"
        case .retryPending: "Retry pending"
        case .needsChanges: "Needs changes"
        case .awaitingReview: "Needs review"
        case .readyToMerge: "Ready to merge"
        case .merging: "Merging"
        case .accepted: "Succeeded"
        case .mergeFailed: "Merge failed"
        case .failed: "Failed"
        case .superseded: "Superseded"
        case .expired: "Expired"
        }
    }

    public var needsAttention: Bool {
        switch self {
        case .recoveryBlocked, .verificationFailed, .needsChanges, .mergeFailed, .failed:
            true
        default:
            false
        }
    }

    public var isActive: Bool {
        switch self {
        case .running, .retryPending, .merging:
            true
        default:
            false
        }
    }
}

public enum AttemptPhase: String, Codable, Sendable {
    case implementation
    case verification
    case publication
    case review
}

public struct TaskSummary: Codable, Identifiable, Equatable, Sendable {
    public let taskID: String
    public let projectID: String
    public let project: String
    public let goal: String?
    public let status: TaskStatus
    public let attemptPhase: AttemptPhase?
    public let attemptCount: Int
    public let createdAt: String?
    public let updatedAt: String?
    public let elapsedSeconds: Int?
    public let branch: String?
    public let commit: String?
    public let headSHA: String?
    public let prURL: String?
    public let lastError: String?
    public let nextAction: String?
    public let projectConfigRevision: Int?
    public let projectConfigSHA256: String?

    public var id: String { taskID }
    public var presentedStatus: String {
        if status == .running, attemptPhase == .verification { return "Verifying" }
        return status.title
    }

    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case projectID = "project_id"
        case project, goal, status
        case attemptPhase = "attempt_phase"
        case attemptCount = "attempt_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case elapsedSeconds = "elapsed_seconds"
        case branch, commit
        case headSHA = "head_sha"
        case prURL = "pr_url"
        case lastError = "last_error"
        case nextAction = "next_action"
        case projectConfigRevision = "project_config_revision"
        case projectConfigSHA256 = "project_config_sha256"
    }

    public init(
        taskID: String,
        projectID: String,
        project: String,
        goal: String? = nil,
        status: TaskStatus,
        attemptPhase: AttemptPhase? = nil,
        attemptCount: Int = 0,
        createdAt: String? = nil,
        updatedAt: String? = nil,
        elapsedSeconds: Int? = nil,
        branch: String? = nil,
        commit: String? = nil,
        headSHA: String? = nil,
        prURL: String? = nil,
        lastError: String? = nil,
        nextAction: String? = nil,
        projectConfigRevision: Int? = nil,
        projectConfigSHA256: String? = nil
    ) {
        self.taskID = taskID
        self.projectID = projectID
        self.project = project
        self.goal = goal
        self.status = status
        self.attemptPhase = attemptPhase
        self.attemptCount = attemptCount
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.elapsedSeconds = elapsedSeconds
        self.branch = branch
        self.commit = commit
        self.headSHA = headSHA
        self.prURL = prURL
        self.lastError = lastError
        self.nextAction = nextAction
        self.projectConfigRevision = projectConfigRevision
        self.projectConfigSHA256 = projectConfigSHA256
    }
}

public struct CoreStatusResponse: Codable, Equatable, Sendable {
    public let status: String
    public let counts: [String: Int]
    public let tasks: [TaskSummary]
}

public struct ProjectSummary: Codable, Identifiable, Equatable, Sendable {
    public let projectID: String
    public let name: String
    public let defaultBranch: String
    public let autoPush: Bool
    public let autoPR: Bool
    public let acceptingTasks: Bool
    public let registered: Bool
    public let configRevision: Int?
    public let configSHA256: String?
    public let configUpdatedAt: String?

    public var id: String { projectID }
    public var shortConfigHash: String? { configSHA256.map { String($0.prefix(12)) } }

    enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case name
        case defaultBranch = "default_branch"
        case autoPush = "auto_push"
        case autoPR = "auto_pr"
        case acceptingTasks = "accepting_tasks"
        case registered
        case configRevision = "config_revision"
        case configSHA256 = "config_sha256"
        case configUpdatedAt = "config_updated_at"
    }
}

public struct ProjectPlan: Codable, Equatable, Sendable {
    public let planToken: String
    public let projectID: String
    public let action: String
    public let currentRevision: Int?
    public let nextRevision: Int?
    public let currentSHA256: String?
    public let nextSHA256: String?
    public let changedFields: [String]
    public let nonterminalTaskCount: Int
    public let taskSnapshotEffect: String

    enum CodingKeys: String, CodingKey {
        case planToken = "plan_token"
        case projectID = "project_id"
        case action
        case currentRevision = "current_revision"
        case nextRevision = "next_revision"
        case currentSHA256 = "current_sha256"
        case nextSHA256 = "next_sha256"
        case changedFields = "changed_fields"
        case nonterminalTaskCount = "nonterminal_task_count"
        case taskSnapshotEffect = "task_snapshot_effect"
    }
}

public struct ProjectMutationResponse: Codable, Equatable, Sendable {
    public let status: String
    public let action: String?
    public let plan: ProjectPlan
    public let project: ProjectSummary?
}

public struct ProjectLifecyclePlan: Codable, Equatable, Sendable {
    public let status: String
    public let projectID: String
    public let action: String
    public let currentAcceptingTasks: Bool
    public let nextAcceptingTasks: Bool
    public let runtimeDataPreserved: Bool
    public let nonterminalTaskCount: Int

    enum CodingKeys: String, CodingKey {
        case status, action
        case projectID = "project_id"
        case currentAcceptingTasks = "current_accepting_tasks"
        case nextAcceptingTasks = "next_accepting_tasks"
        case runtimeDataPreserved = "runtime_data_preserved"
        case nonterminalTaskCount = "nonterminal_task_count"
    }
}

public struct ProjectLifecycleAppliedResponse: Codable, Equatable, Sendable {
    public let status: String
    public let plan: ProjectLifecyclePlan
    public let project: ProjectSummary
}

public struct ServiceItem: Codable, Identifiable, Equatable, Sendable {
    public let name: String
    public let label: String
    public let state: String
    public let installed: Bool
    public let lastExitCode: Int?

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, label, state, installed
        case lastExitCode = "last_exit_code"
    }
}

public struct ServiceStatusResponse: Codable, Equatable, Sendable {
    public let status: String
    public let helperExecutable: Bool
    public let services: [ServiceItem]

    enum CodingKeys: String, CodingKey {
        case status, services
        case helperExecutable = "helper_executable"
    }
}

public struct ActionResponse: Codable, Equatable, Sendable {
    public let status: String
    public let runtimePreserved: Bool?
    public let services: [String]?
    public let removed: [String]?

    enum CodingKeys: String, CodingKey {
        case status, services, removed
        case runtimePreserved = "runtime_preserved"
    }
}

public struct HealthCheck: Codable, Identifiable, Equatable, Sendable {
    public let name: String
    public let status: String
    public let detail: String

    public var id: String { name }
    public var passed: Bool { status == "passed" }
}

public struct HealthResponse: Codable, Equatable, Sendable {
    public let status: String
    public let checks: [HealthCheck]
}

public struct RuntimeInitResponse: Codable, Equatable, Sendable {
    public let status: String
    public let schemaVersion: Int
    public let checks: [String: Bool]

    enum CodingKeys: String, CodingKey {
        case status, checks
        case schemaVersion = "schema_version"
    }
}

public struct VerificationEvidence: Codable, Identifiable, Equatable, Sendable {
    public let verificationID: Int?
    public let criterionID: String?
    public let criterionText: String?
    public let status: String?
    public let evidenceSummary: String?
    public let exitCode: Int?

    public var id: String {
        verificationID.map(String.init) ?? "\(criterionID ?? "criterion")-\(status ?? "unknown")"
    }

    enum CodingKeys: String, CodingKey {
        case verificationID = "verification_id"
        case criterionID = "criterion_id"
        case criterionText = "criterion_text"
        case status
        case evidenceSummary = "evidence_summary"
        case exitCode = "exit_code"
    }
}

public struct ReviewFinding: Codable, Identifiable, Equatable, Sendable {
    public let severity: String
    public let file: String?
    public let evidence: String
    public let requirement: String

    public var id: String { "\(severity)-\(file ?? "general")-\(requirement)" }
}

public struct ReviewSummary: Codable, Identifiable, Equatable, Sendable {
    public let reviewID: Int?
    public let headSHA: String?
    public let verdict: String?
    public let findings: [ReviewFinding]?

    public var id: String { reviewID.map(String.init) ?? "\(headSHA ?? "review")-\(verdict ?? "")" }

    enum CodingKeys: String, CodingKey {
        case reviewID = "review_id"
        case headSHA = "head_sha"
        case verdict, findings
    }
}

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    public var displayText: String {
        switch self {
        case .string(let value): value
        case .number(let value): String(format: "%g", value)
        case .bool(let value): value ? "Yes" : "No"
        case .object(let value): value["text"]?.displayText ?? value["criterion"]?.displayText ?? "Detail"
        case .array(let value): value.map(\.displayText).joined(separator: ", ")
        case .null: "—"
        }
    }
}

public struct TaskEvent: Codable, Identifiable, Equatable, Sendable {
    public let eventID: Int
    public let eventType: String
    public let payload: [String: JSONValue]
    public let createdAt: String

    public var id: Int { eventID }

    enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case eventType = "event_type"
        case payload
        case createdAt = "created_at"
    }
}

public struct TaskDetail: Codable, Equatable, Sendable {
    public let taskID: String
    public let projectID: String
    public let project: String
    public let goal: String?
    public let status: TaskStatus
    public let attemptPhase: AttemptPhase?
    public let attemptCount: Int
    public let branch: String?
    public let commit: String?
    public let headSHA: String?
    public let prURL: String?
    public let lastError: String?
    public let nextAction: String?
    public let acceptanceCriteria: [JSONValue]
    public let verification: [VerificationEvidence]
    public let reviews: [ReviewSummary]
    public let events: [TaskEvent]

    public var changedFiles: [String] {
        for event in events.reversed() {
            if case .array(let values)? = event.payload["changed_files"] {
                return values.compactMap { if case .string(let value) = $0 { value } else { nil } }
            }
        }
        return []
    }

    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case projectID = "project_id"
        case project, goal, status
        case attemptPhase = "attempt_phase"
        case attemptCount = "attempt_count"
        case branch, commit
        case headSHA = "head_sha"
        case prURL = "pr_url"
        case lastError = "last_error"
        case nextAction = "next_action"
        case acceptanceCriteria = "acceptance_criteria"
        case verification, reviews, events
    }
}

public enum AggregateStatus: String, Codable, Sendable {
    case healthy = "Healthy"
    case running = "Running"
    case needsAttention = "Needs attention"
    case offline = "Offline"
}

public struct MenuBarSnapshot: Equatable, Sendable {
    public let status: AggregateStatus
    public let counts: [String: Int]
    public let services: [ServiceItem]

    public static func make(tasks: [TaskSummary], service: ServiceStatusResponse?) -> Self {
        let counts = Dictionary(grouping: tasks, by: { $0.status.rawValue }).mapValues(\.count)
        let serviceOffline = service == nil || ["not_installed", "unhealthy"].contains(service?.status)
        let status: AggregateStatus
        if serviceOffline {
            status = .offline
        } else if tasks.contains(where: { $0.status.needsAttention }) {
            status = .needsAttention
        } else if tasks.contains(where: { $0.status.isActive }) {
            status = .running
        } else {
            status = .healthy
        }
        return Self(status: status, counts: counts, services: service?.services ?? [])
    }
}
