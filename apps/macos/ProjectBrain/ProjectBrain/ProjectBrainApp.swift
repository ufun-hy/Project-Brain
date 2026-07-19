import AppKit
import SwiftUI

@main
struct ProjectBrainApp: App {
    @NSApplicationDelegateAdaptor(ApplicationInstanceCoordinator.self)
    private var applicationInstanceCoordinator
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = AppModel()

    init() {
        _ = Build9LocalTaskAppProbe.runIfRequested()
    }

    var body: some Scene {
        Window("Project Brain", id: "management") {
            ManagementView(model: model)
                .frame(minWidth: 980, minHeight: 680)
                .task {
                    let environment = ProcessInfo.processInfo.environment
                    if environment["CI"] != "true"
                        || environment["PROJECT_BRAIN_UI_TEST_MODE"] != "1" {
                        model.bootstrap()
                    }
                }
                .onChange(of: scenePhase) { _, phase in
                    model.setApplicationActive(phase == .active)
                }
                .onReceive(NotificationCenter.default.publisher(
                    for: NSApplication.willTerminateNotification
                )) { _ in
                    model.shutdown()
                }
        }
        .defaultSize(width: 1120, height: 760)

        MenuBarExtra {
            MenuBarView(model: model)
        } label: {
            Label("Project Brain", systemImage: menuSymbol)
        }
        .menuBarExtraStyle(.window)
    }

    private var menuSymbol: String {
        switch model.menuSnapshot.status {
        case .healthy: "brain.head.profile.fill"
        case .running: "brain"
        case .needsAttention: "exclamationmark.triangle.fill"
        case .offline: "brain.head.profile"
        }
    }
}
