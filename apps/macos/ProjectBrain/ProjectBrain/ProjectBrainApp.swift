import SwiftUI

@main
struct ProjectBrainApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Project Brain", id: "management") {
            ManagementView(model: model)
                .frame(minWidth: 980, minHeight: 680)
                .task { model.bootstrap() }
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
