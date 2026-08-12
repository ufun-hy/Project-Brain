import Foundation

public final class FirstTaskGuideStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    public init(
        defaults: UserDefaults = .standard,
        key: String = "productShell.firstTaskGuide.v1"
    ) {
        self.defaults = defaults
        self.key = key
    }

    public func shouldPresent(taskCount: Int) -> Bool {
        taskCount == 0 && !defaults.bool(forKey: key)
    }

    public func markPresented() {
        defaults.set(true, forKey: key)
    }
}
