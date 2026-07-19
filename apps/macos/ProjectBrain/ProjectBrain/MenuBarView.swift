import ProjectBrainKit
import SwiftUI

struct MenuBarView: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                StatusDot(status: model.menuSnapshot.status)
                VStack(alignment: .leading) {
                    Text(model.menuSnapshot.status.rawValue).font(.headline)
                    Text(serviceSummary).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.borderless)
                    .disabled(model.isBusy)
            }

            if model.tasks.filter({ $0.status.isActive }).isEmpty {
                Text("No task is currently running.").foregroundStyle(.secondary)
            } else {
                ForEach(model.tasks.filter { $0.status.isActive }.prefix(3)) { task in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(task.goal ?? task.taskID).lineLimit(1)
                        Text("\(task.presentedStatus) · attempt \(task.attemptCount)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }

            HStack(spacing: 16) {
                count("Pending", statuses: [.pending, .retryPending])
                count("Running", statuses: [.running, .merging])
                count("Review", statuses: [.awaitingReview, .readyToMerge])
                count("Failed", statuses: [.failed, .verificationFailed, .mergeFailed])
            }

            if !model.projects.isEmpty {
                Divider()
                Menu {
                    ForEach(model.projects) { project in
                        Button {
                            model.selectedProjectID = project.projectID
                        } label: {
                            if model.selectedProjectID == project.projectID {
                                Label(project.name, systemImage: "checkmark")
                            } else {
                                Text(project.name)
                            }
                        }
                    }
                } label: {
                    Label(selectedProjectName, systemImage: "folder")
                }
                Menu("Project intake") {
                    ForEach(model.projects) { project in
                        Button(project.acceptingTasks ? "Pause \(project.name)" : "Resume \(project.name)") {
                            model.planLifecycle(
                                projectID: project.projectID,
                                action: project.acceptingTasks ? .pause : .resume
                            )
                        }
                    }
                }
            }

            Divider()
            Button("New Task…") {
                model.selectedSection = .tasks
                model.openNewTask(defaultProjectID: model.selectedProjectID)
                openWindow(id: "management")
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.projects.isEmpty)
            .help(
                model.projects.isEmpty
                    ? String(localized: "Add a project first")
                    : String(localized: "Create a local task")
            )
            .accessibilityIdentifier("menu-bar-new-task")
            HStack {
                Button("Open Task Center") {
                    model.selectedSection = .tasks
                    openWindow(id: "management")
                }
                Button("Diagnostics") {
                    model.selectedSection = .diagnostics
                    openWindow(id: "management")
                }
            }

            Divider()
            Button("Quit Project Brain", role: .destructive) {
                model.quitApplication()
            }
            .keyboardShortcut("q")
            .accessibilityIdentifier("menu-bar-quit-project-brain")
        }
        .padding(16)
        .frame(width: 390)
    }

    private var serviceSummary: String {
        let states = model.services?.services.map { "\($0.name): \($0.state)" } ?? []
        return states.isEmpty ? "Worker and MCP offline" : states.joined(separator: " · ")
    }

    private var selectedProjectName: String {
        model.projects.first(where: { $0.projectID == model.selectedProjectID })?.name
            ?? model.projects.first?.name
            ?? String(localized: "No project")
    }

    @ViewBuilder private func count(_ title: String, statuses: Set<TaskStatus>) -> some View {
        VStack {
            Text(String(model.tasks.filter { statuses.contains($0.status) }.count)).font(.title3.bold())
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }
}
