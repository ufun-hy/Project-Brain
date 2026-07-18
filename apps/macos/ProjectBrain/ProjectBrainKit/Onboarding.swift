import Foundation

public enum ApplicationInstallationLocation: String, Equatable, Sendable {
    case applications
    case diskImage
    case other
}

public struct ApplicationInstallationStatus: Equatable, Sendable {
    public static let requiredBundleURL = URL(filePath: "/Applications/Project Brain.app")

    public let bundleURL: URL
    public let location: ApplicationInstallationLocation

    public init(bundleURL: URL) {
        let canonical = bundleURL.standardizedFileURL
        self.bundleURL = canonical
        if canonical.path == Self.requiredBundleURL.standardizedFileURL.path {
            self.location = .applications
        } else if canonical.path == "/Volumes" || canonical.path.hasPrefix("/Volumes/") {
            self.location = .diskImage
        } else {
            self.location = .other
        }
    }

    public var isInstalled: Bool { location == .applications }

    public var title: String {
        switch location {
        case .applications: "Installed in Applications"
        case .diskImage: "Project Brain is not installed"
        case .other: "Project Brain is running outside Applications"
        }
    }

    public var guidance: String {
        switch location {
        case .applications:
            "Project Brain is running from /Applications/Project Brain.app."
        case .diskImage:
            "Quit the app, drag Project Brain.app from the DMG into /Applications, eject the DMG, then open /Applications/Project Brain.app."
        case .other:
            "Move Project Brain.app to /Applications, then open /Applications/Project Brain.app before formal acceptance."
        }
    }
}

public enum OnboardingStage: String, Codable, CaseIterable, Sendable {
    case welcome
    case runtime
    case project
    case plan
    case services
    case health
    case ready

    public var title: String {
        switch self {
        case .welcome: "Welcome"
        case .runtime: "Local runtime"
        case .project: "First project"
        case .plan: "Confirm configuration"
        case .services: "Background services"
        case .health: "Local health check"
        case .ready: "Ready"
        }
    }
}

public struct OnboardingProgress: Codable, Equatable, Sendable {
    public var stage: OnboardingStage
    public var completed: Bool
    public var selectedRepository: String?
    public var projectPlanSHA256: String?
    public var lastError: String?

    public init(
        stage: OnboardingStage = .welcome,
        completed: Bool = false,
        selectedRepository: String? = nil,
        projectPlanSHA256: String? = nil,
        lastError: String? = nil
    ) {
        self.stage = stage
        self.completed = completed
        self.selectedRepository = selectedRepository
        self.projectPlanSHA256 = projectPlanSHA256
        self.lastError = lastError
    }
}

public final class OnboardingStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    public init(defaults: UserDefaults = .standard, key: String = "productShell.onboarding.v1") {
        self.defaults = defaults
        self.key = key
    }

    public func load() -> OnboardingProgress {
        guard let data = defaults.data(forKey: key),
              let value = try? JSONDecoder().decode(OnboardingProgress.self, from: data) else {
            return OnboardingProgress()
        }
        return value
    }

    public func save(_ progress: OnboardingProgress) {
        guard let data = try? JSONEncoder().encode(progress) else { return }
        defaults.set(data, forKey: key)
    }
}
