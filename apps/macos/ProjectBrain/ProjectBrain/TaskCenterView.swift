import AppKit
import ProjectBrainKit
import SwiftUI

struct TaskCenterView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        NavigationSplitView {
            List(model.tasks) { task in
                Button { model.selectTask(task) } label: {
                    TaskRow(task: task)
                }
                .buttonStyle(.plain)
            }
            .overlay {
                if model.tasks.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "checklist").font(.largeTitle)
                        Text("No tasks yet").font(.title2.bold())
                        Text("Project Brain is ready for a new task.")
                            .foregroundStyle(.secondary)
                        Button("Create Task") { model.openNewTask() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.projects.isEmpty)
                            .accessibilityIdentifier("task-center-empty-create-task")
                    }
                }
            }
            .navigationTitle("Task Center")
            .navigationSplitViewColumnWidth(min: 320, ideal: 380)
            .toolbar {
                Button("New Task", systemImage: "plus") { model.openNewTask() }
                    .disabled(model.projects.isEmpty)
                    .accessibilityIdentifier("task-center-new-task")
            }
        } detail: {
            if let detail = model.selectedTask {
                TaskDetailView(task: detail)
            } else {
                VStack(alignment: .leading, spacing: 18) {
                    Text("Create and follow a task").font(.title2.bold())
                    Label("Describe the outcome.", systemImage: "1.circle")
                    Label("Review the execution plan.", systemImage: "2.circle")
                    Label("Follow progress and review the result.", systemImage: "3.circle")
                }
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .sheet(isPresented: $model.isNewTaskPresented) {
            NewTaskView(model: model)
        }
        .alert("Your first project is ready", isPresented: $model.shouldShowFirstTaskGuide) {
            Button("Create First Task") { model.createFirstTaskFromGuide() }
            Button("Not now", role: .cancel) { model.skipFirstTaskGuide() }
        } message: {
            Text("Project Brain works in an isolated Git worktree and keeps your main checkout untouched.")
        }
    }
}

private struct TaskRow: View {
    let task: TaskSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(task.goal ?? task.taskID).font(.headline).lineLimit(1)
                Spacer()
                StatusBadge(status: task.status, text: task.presentedStatus)
            }
            Text("\(task.project) · \(source) · \(task.localTaskType?.title ?? String(localized: "Task"))")
                .font(.caption).foregroundStyle(.secondary)
            Text(String(
                format: String(localized: "Task row metadata format"),
                task.attemptPhase?.rawValue.capitalized ?? "—",
                task.createdAt ?? "—",
                task.updatedAt ?? "—"
            ))
            .font(.caption2)
            .foregroundStyle(.secondary)
            if let next = task.nextAction {
                Text(next).font(.caption).lineLimit(2)
            }
        }
        .padding(.vertical, 5)
    }

    private var source: String {
        switch task.sourceType {
        case "local_app": String(localized: "App")
        case "mcp", "chatgpt": String(localized: "ChatGPT")
        case .some(let value): value
        case .none: String(localized: "Existing source")
        }
    }
}

private struct TaskDetailView: View {
    let task: TaskDetail

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(task.goal ?? task.taskID).font(.largeTitle.bold())
                        Text("\(task.project) · \(task.taskID)").foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusBadge(status: task.status, text: task.status.title)
                }

                GroupBox("Execution") {
                    LabeledContent("Source", value: source)
                    LabeledContent(
                        "Task type",
                        value: task.localTaskType?.title ?? String(localized: "Existing task")
                    )
                    LabeledContent("Phase", value: task.attemptPhase?.rawValue.capitalized ?? "—")
                    LabeledContent("Attempt", value: String(task.attemptCount))
                    LabeledContent("Created", value: task.createdAt ?? "—")
                    LabeledContent("Updated", value: task.updatedAt ?? "—")
                    LabeledContent("Branch", value: task.branch ?? "—")
                    LabeledContent("Canonical commit", value: task.commit ?? task.headSHA ?? "—")
                    LabeledContent("Base SHA", value: task.baseSHA ?? "—")
                    if let revision = task.projectConfigRevision {
                        LabeledContent(
                            "Execution profile",
                            value: "revision \(revision) · \(task.projectConfigSHA256 ?? "—")"
                        )
                    }
                    if let url = task.prURL, let destination = URL(string: url) {
                        LabeledContent("Draft PR") {
                            Button(url) { NSWorkspace.shared.open(destination) }
                                .buttonStyle(.link)
                        }
                    }
                }

                if let result = task.result {
                    GroupBox(task.localTaskType == .analysis ? "Analysis result" : "Execution result") {
                        VStack(alignment: .leading, spacing: 8) {
                            if let summary = result["summary"] {
                                Text(summary.displayText).textSelection(.enabled)
                            }
                            if let kind = result["kind"] {
                                LabeledContent("Result type", value: kind.displayText)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if let delivery = task.delivery {
                    GroupBox("Delivery snapshot") {
                        LabeledContent("Commit", value: yesNo(delivery.commit))
                        LabeledContent("Push", value: yesNo(delivery.push))
                        LabeledContent("Draft PR", value: yesNo(delivery.draftPR))
                    }
                }

                if !task.changedFiles.isEmpty {
                    GroupBox("Changed files") {
                        VStack(alignment: .leading, spacing: 5) {
                            ForEach(task.changedFiles, id: \.self) { Text($0).font(.system(.body, design: .monospaced)) }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if !task.acceptanceCriteria.isEmpty {
                    GroupBox("Verification criteria") {
                        VStack(alignment: .leading, spacing: 7) {
                            ForEach(Array(task.acceptanceCriteria.enumerated()), id: \.offset) { index, item in
                                Label(item.displayText, systemImage: "circle.dashed")
                                    .accessibilityLabel("Criterion \(index + 1): \(item.displayText)")
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                GroupBox("Verification evidence") {
                    if task.verification.isEmpty {
                        Text("No verification evidence has been recorded.").foregroundStyle(.secondary)
                    } else {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(task.verification) { evidence in
                                HStack(alignment: .top) {
                                    Image(systemName: evidence.status == "passed" ? "checkmark.circle.fill" : "xmark.circle.fill")
                                        .foregroundStyle(evidence.status == "passed" ? .green : .red)
                                    VStack(alignment: .leading) {
                                        Text(evidence.criterionText ?? evidence.criterionID ?? "Verification")
                                            .font(.headline)
                                        Text(evidence.evidenceSummary ?? "No summary")
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }

                if let seal = task.verificationSet {
                    GroupBox("Verification seal") {
                        VStack(alignment: .leading, spacing: 6) {
                            LabeledContent("Status", value: seal.status.capitalized)
                            LabeledContent("Canonical head", value: short(seal.canonicalHeadSHA))
                            LabeledContent("Attempt", value: String(seal.sourceAttemptNumber))
                            LabeledContent("Verification set", value: String(seal.verificationSetID))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if !task.reviews.isEmpty {
                    GroupBox("Review findings") {
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(task.reviews) { review in
                                Text(review.verdict?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Review")
                                    .font(.headline)
                                ForEach(review.findings ?? []) { finding in
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text("[\(finding.severity.uppercased())] \(finding.requirement)")
                                        Text(finding.evidence).foregroundStyle(.secondary)
                                        if let file = finding.file { Text(file).font(.caption.monospaced()) }
                                    }
                                }
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                if let error = task.lastError {
                    GroupBox("Last error") {
                        Text(error).foregroundStyle(.red).textSelection(.enabled)
                    }
                }
                if let next = task.nextAction {
                    GroupBox("Next action") { Text(next) }
                }

                if !task.events.isEmpty {
                    GroupBox("Phase timeline") {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(task.events) { event in
                                HStack(alignment: .top) {
                                    Image(systemName: "circle.fill").font(.system(size: 6))
                                    VStack(alignment: .leading) {
                                        Text(event.eventType.replacingOccurrences(of: "_", with: " ").capitalized)
                                        Text(event.createdAt).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .padding(28)
        }
    }

    private func short(_ value: String?) -> String {
        value.map { String($0.prefix(12)) } ?? "—"
    }

    private var source: String {
        switch task.sourceType {
        case "local_app": String(localized: "App")
        case "mcp", "chatgpt": String(localized: "ChatGPT")
        case .some(let value): value
        case .none: String(localized: "Existing source")
        }
    }

    private func yesNo(_ value: Bool) -> String {
        value ? String(localized: "Yes") : String(localized: "No")
    }
}

struct StatusBadge: View {
    let status: TaskStatus
    let text: String

    var body: some View {
        Text(text)
            .font(.caption.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.16), in: Capsule())
            .foregroundStyle(color)
    }

    private var color: Color {
        if status.needsAttention { return .orange }
        if status.isActive { return .blue }
        if status == .accepted || status == .completed { return .green }
        return .secondary
    }
}
