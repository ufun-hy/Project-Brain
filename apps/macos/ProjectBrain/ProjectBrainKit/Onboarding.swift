import Foundation

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
