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
    case serviceStatus
    case service(ServiceAction)
    case addProject(ProjectDraft, execute: Bool)
    case updateProject(String, ProjectUpdateDraft, execute: Bool)
    case projectLifecycle(String, ProjectLifecycleAction, execute: Bool)

    public var acceptedExitCodes: Set<Int32> {
        switch self {
        case .health: [0, 1]
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
        case .serviceStatus:
            value += ["service", "status", "--json"]
        case .service(let action):
            value += ["service", action.rawValue, "--json"]
        case .addProject(let draft, let execute):
            value += ["projects", "add", draft.repository.path]
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
            value += [execute ? "--non-interactive" : "--plan", "--json"]
        case .updateProject(let identifier, let draft, let execute):
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
            value += [execute ? "--non-interactive" : "--plan", "--json"]
        case .projectLifecycle(let identifier, let action, let execute):
            value += ["projects", action.rawValue, identifier]
            if execute { value.append("--execute") }
            value.append("--json")
        }
        return value
    }
}
