import AppKit
import Foundation
import ProjectBrainKit

final class ApplicationInstanceCoordinator: NSObject, NSApplicationDelegate {
    private var processLock: UserProcessLock?
    private var ownsInstance = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        do {
            guard let lock = try UserProcessLock.acquire(at: Self.lockURL()) else {
                activateExistingInstance()
                DispatchQueue.main.async { NSApp.terminate(nil) }
                return
            }
            processLock = lock
            ownsInstance = true
        } catch {
            // Fail closed when user-level instance ownership cannot be proven.
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard ownsInstance else { return }
        ApplicationUITestProbe.startIfEnabled()
    }

    private func activateExistingInstance() {
        guard let identifier = Bundle.main.bundleIdentifier else { return }
        let currentPID = ProcessInfo.processInfo.processIdentifier
        NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
            .first(where: { $0.processIdentifier != currentPID })?
            .activate(options: [.activateAllWindows])
    }

    private static func lockURL() -> URL {
        let environment = ProcessInfo.processInfo.environment
        if environment["CI"] == "true",
           environment["PROJECT_BRAIN_UI_TEST_MODE"] == "1",
           let override = environment["PROJECT_BRAIN_INSTANCE_LOCK_PATH"],
           override.hasPrefix("/") {
            return URL(filePath: override)
        }
        return FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0].appending(path: "Project Brain/app-instance.lock")
    }
}

@MainActor
private enum ApplicationUITestProbe {
    private static var timer: Timer?

    static func startIfEnabled() {
        let environment = ProcessInfo.processInfo.environment
        guard environment["CI"] == "true",
              environment["PROJECT_BRAIN_UI_TEST_MODE"] == "1",
              let path = environment["PROJECT_BRAIN_UI_PROBE_PATH"],
              path.hasPrefix("/") else { return }
        let url = URL(filePath: path)
        write(to: url)
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { _ in
            Task { @MainActor in write(to: url) }
        }
    }

    private static func write(to url: URL) {
        let managementWindows = NSApp.windows.filter {
            $0.title == "Project Brain" && $0.isVisible
        }
        let value: [String: Any] = [
            "pid": ProcessInfo.processInfo.processIdentifier,
            "management_window_count": managementWindows.count,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: value,
            options: [.sortedKeys]
        ) else { return }
        try? data.write(to: url, options: .atomic)
    }
}
