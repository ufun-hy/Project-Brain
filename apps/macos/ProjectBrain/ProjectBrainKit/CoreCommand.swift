import Foundation

public enum ServiceAction: String, CaseIterable, Sendable {
    case install
    case start
    case stop
    case restart
    case uninstall
}

public enum ProjectLifecycleAction: String, Sendable {
    case pause
    case resume
    case remove
}

public struct ProjectDraft: Equatable, Sendable {
    public let repository: URL
    public var projectID: String?
    public var name: String?
    public var defaultBranch: String?
    public var codexExecutable: URL?
    public var verificationFile: URL?
    public var autoPush: Bool
    public var autoPR: Bool

    public init(
        repository: URL,
        projectID: String? = nil,
        name: String? = nil,
        defaultBranch: String? = nil,
        codexExecutable: URL? = nil,
        verificationFile: URL? = nil,
        autoPush: Bool = true,
        autoPR: Bool = true
    ) {
        self.repository = repository
        self.projectID = projectID
        self.name = name
        self.defaultBranch = defaultBranch
        self.codexExecutable = codexExecutable
        self.verificationFile = verificationFile
        self.autoPush = autoPush
        self.autoPR = autoPR
    }
}

public struct ProjectUpdateDraft: Equatable, Sendable {
    public var name: String?
    public var defaultBranch: String?
    public var codexExecutable: URL?
    public var verificationFile: URL?
    public var autoPush: Bool?
    public var autoPR: Bool?

    public init(
        name: String? = nil,
        defaultBranch: String? = nil,
        codexExecutable: URL? = nil,
        verificationFile: URL? = nil,
        autoPush: Bool? = nil,
        autoPR: Bool? = nil
    ) {
        self.name = name
        self.defaultBranch = defaultBranch
        self.codexExecutable = codexExecutable
        self.verificationFile = verificationFile
        self.autoPush = autoPush
        self.autoPR = autoPR
    }
}

public enum CoreCommand: Equatable, Sendable {
    case initialize
    case status
    case tasks
    case task(String)
    case projects
    case health
    case readiness
    case serviceStatus
    case service(ServiceAction)
    case addProject(ProjectDraft, planToken: String?)
    case useProject(String, planToken: String?)
    case updateProject(String, ProjectUpdateDraft, planToken: String?)
    case projectLifecycle(String, ProjectLifecycleAction, execute: Bool)
    case acceptanceStatus
    case acceptanceCreate(appVersion: String, tunnelFingerprint: String)
    case acceptanceWaiting(String)
    case acceptanceReset(String)
    case acceptanceTaskPlan(String)
    case acceptanceTaskCreate(String, planToken: String)

    public var acceptedExitCodes: Set<Int32> {
        switch self {
        case .health, .readiness: [0, 1]
        default: [0]
        }
    }

    public func arguments(runtimeRoot: URL) -> [String] {
        var value = ["--runtime-root", runtimeRoot.path]
        switch self {
        case .initialize:
            value += ["init", "--json"]
        case .status:
            value += ["status", "--json"]
        case .tasks:
            value += ["tasks", "list", "--limit", "200", "--json"]
        case .task(let identifier):
            value += ["tasks", "show", identifier, "--json"]
        case .projects:
            value += ["projects", "list", "--json"]
        case .health:
            value += ["health", "--json"]
        case .readiness:
            value += ["readiness", "--json"]
        case .serviceStatus:
            value += ["service", "status", "--json"]
        case .service(let action):
            value += ["service", action.rawValue, "--json"]
        case .addProject(let draft, let planToken):
            value += ["projects", "add", draft.repository.path, "--resolve-existing"]
            if let projectID = draft.projectID, !projectID.isEmpty {
                value += ["--project-id", projectID]
            }
            if let name = draft.name, !name.isEmpty { value += ["--name", name] }
            if let branch = draft.defaultBranch, !branch.isEmpty {
                value += ["--default-branch", branch]
            }
            if let codex = draft.codexExecutable { value += ["--codex-path", codex.path] }
            if let checks = draft.verificationFile {
                value += ["--verification-file", checks.path]
            }
            value += [draft.autoPush ? "--auto-push" : "--no-auto-push"]
            value += [draft.autoPR ? "--auto-pr" : "--no-auto-pr"]
            if let planToken {
                value += ["--non-interactive", "--plan-token", planToken]
            } else {
                value.append("--plan")
            }
            value.append("--json")
        case .useProject(let identifier, let planToken):
            value += ["projects", "use", identifier]
            if let planToken {
                value += ["--non-interactive", "--plan-token", planToken]
            } else {
                value.append("--plan")
            }
            value.append("--json")
        case .updateProject(let identifier, let draft, let planToken):
            value += ["projects", "update", identifier]
            if let name = draft.name, !name.isEmpty { value += ["--name", name] }
            if let branch = draft.defaultBranch, !branch.isEmpty {
                value += ["--default-branch", branch]
            }
            if let codex = draft.codexExecutable { value += ["--codex-path", codex.path] }
            if let checks = draft.verificationFile {
                value += ["--verification-file", checks.path]
            }
            if let autoPush = draft.autoPush {
                value.append(autoPush ? "--auto-push" : "--no-auto-push")
            }
            if let autoPR = draft.autoPR {
                value.append(autoPR ? "--auto-pr" : "--no-auto-pr")
            }
            if let planToken {
                value += ["--non-interactive", "--plan-token", planToken]
            } else {
                value.append("--plan")
            }
            value.append("--json")
        case .projectLifecycle(let identifier, let action, let execute):
            value += ["projects", action.rawValue, identifier]
            if execute { value.append("--execute") }
            value.append("--json")
        case .acceptanceStatus:
            value += ["acceptance", "status", "--json"]
        case .acceptanceCreate(let appVersion, let tunnelFingerprint):
            value += [
                "acceptance", "create",
                "--app-version", appVersion,
                "--tunnel-fingerprint", tunnelFingerprint,
                "--json",
            ]
        case .acceptanceWaiting(let runID):
            value += ["acceptance", "waiting", runID, "--json"]
        case .acceptanceReset(let runID):
            value += ["acceptance", "reset", runID, "--json"]
        case .acceptanceTaskPlan(let projectID):
            value += ["acceptance", "task-plan", projectID, "--json"]
        case .acceptanceTaskCreate(let projectID, let planToken):
            value += [
                "acceptance", "task-create", projectID,
                "--plan-token", planToken,
                "--json",
            ]
        }
        return value
    }
}
