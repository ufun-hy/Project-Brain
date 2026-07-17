import ProjectBrainKit
import SwiftUI

struct ManagementView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        NavigationSplitView {
            List(ProductSection.allCases, selection: $model.selectedSection) { section in
                Label(section.rawValue, systemImage: section.symbol)
                    .tag(section)
            }
            .navigationTitle("Project Brain")
            .safeAreaInset(edge: .bottom) {
                HStack {
                    StatusDot(status: model.menuSnapshot.status)
                    Text(model.menuSnapshot.status.rawValue)
                        .font(.caption)
                    Spacer()
                }
                .padding()
                .background(.bar)
            }
        } detail: {
            sectionView
        }
        .toolbar {
            ToolbarItem {
                Button {
                    model.refresh()
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(model.isBusy || !model.onboarding.completed)
            }
        }
        .sheet(isPresented: Binding(
            get: { !model.onboarding.completed },
            set: { _ in }
        )) {
            OnboardingView(model: model)
                .interactiveDismissDisabled()
        }
        .alert(item: $model.issue) { issue in
            Alert(
                title: Text(issue.title),
                message: Text("\(issue.message)\n\nNext: \(issue.nextAction)"),
                dismissButton: .default(Text("OK"))
            )
        }
        .overlay {
            if model.isBusy {
                ZStack {
                    Color.black.opacity(0.08).ignoresSafeArea()
                    ProgressView().controlSize(.large)
                }
            }
        }
    }

    @ViewBuilder private var sectionView: some View {
        switch model.selectedSection {
        case .tasks: TaskCenterView(model: model)
        case .projects: ProjectsView(model: model)
        case .connection: ConnectionCenterView(model: model)
        case .diagnostics: DiagnosticsView(model: model)
        case .settings: SettingsView(model: model)
        }
    }
}

struct StatusDot: View {
    let status: ProjectBrainKit.AggregateStatus

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 9, height: 9)
            .accessibilityLabel(status.rawValue)
    }

    private var color: Color {
        switch status {
        case .healthy: .green
        case .running: .blue
        case .needsAttention: .orange
        case .offline: .secondary
        }
    }
}
