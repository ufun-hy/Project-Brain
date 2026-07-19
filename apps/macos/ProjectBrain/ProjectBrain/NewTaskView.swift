import ProjectBrainKit
import SwiftUI

struct NewTaskView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Label(
                    model.localTaskPlan == nil ? "New Task" : "Review Execution Plan",
                    systemImage: model.localTaskPlan == nil ? "plus.circle" : "doc.text.magnifyingglass"
                )
                .font(.title2.bold())
                Spacer()
                Button("Cancel") {
                    model.isNewTaskPresented = false
                    dismiss()
                }
                .disabled(model.isBusy)
            }
            .padding(22)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let issue = model.localTaskIssue {
                        LocalTaskInlineIssue(issue: issue, model: model)
                    }
                    if let response = model.localTaskPlan {
                        LocalTaskPlanView(plan: response.plan)
                    } else {
                        LocalTaskForm(model: model)
                    }
                }
                .padding(24)
            }

            Divider()

            HStack {
                if model.localTaskPlan != nil {
                    Button("Back to edit") { model.reviewNewLocalTaskPlan() }
                }
                Spacer()
                if let plan = model.localTaskPlan {
                    if !plan.plan.readiness.ready {
                        Button("Open Diagnostics") { model.openDiagnosticsFromLocalTask() }
                    }
                    Button("Confirm and Create Task") { model.createLocalTask() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isBusy || !plan.plan.readiness.ready)
                        .accessibilityIdentifier("local-task-confirm")
                } else {
                    Button("Review Execution Plan") { model.planLocalTask() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isBusy || !formIsValid)
                        .accessibilityIdentifier("local-task-review-plan")
                }
            }
            .padding(20)
        }
        .frame(width: 760, height: 700)
        .interactiveDismissDisabled(model.isBusy)
    }

    private var formIsValid: Bool {
        let goal = model.localTaskRequest.goal.trimmingCharacters(in: .whitespacesAndNewlines)
        let criteriaCount = model.localTaskRequest.acceptanceCriteria.reduce(0) {
            $0 + $1.trimmingCharacters(in: .whitespacesAndNewlines).count
        }
        return !model.localTaskRequest.projectID.isEmpty
            && (10...8_000).contains(goal.count)
            && criteriaCount <= 8_000
            && model.localTaskRequest.acceptanceCriteria.count <= 100
    }
}

private struct LocalTaskForm: View {
    @ObservedObject var model: AppModel

    var body: some View {
        GroupBox("Task") {
            VStack(alignment: .leading, spacing: 16) {
                Picker("Project", selection: Binding(
                    get: { model.localTaskRequest.projectID },
                    set: { model.selectLocalTaskProject($0) }
                )) {
                    ForEach(model.projects.filter(\.acceptingTasks)) { project in
                        Text(project.name).tag(project.projectID)
                    }
                }

                Picker("Task type", selection: Binding(
                    get: { model.localTaskRequest.taskType },
                    set: { model.updateLocalTaskType($0) }
                )) {
                    Text("Analyze / Review").tag(LocalTaskType.analysis)
                    Text("Implement change").tag(LocalTaskType.implement)
                }
                .pickerStyle(.segmented)

                VStack(alignment: .leading, spacing: 6) {
                    Text("Goal").font(.headline)
                    TextEditor(text: $model.localTaskRequest.goal)
                        .font(.body)
                        .frame(minHeight: 130)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                        .accessibilityIdentifier("local-task-goal")
                    Text("\(model.localTaskRequest.goal.count) / 8,000 characters; minimum 10")
                        .font(.caption)
                        .foregroundStyle(goalIsValid ? Color.secondary : Color.red)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Acceptance criteria").font(.headline)
                    Text("Optional. Put one criterion on each line.")
                        .font(.caption).foregroundStyle(.secondary)
                    TextEditor(text: criteriaBinding)
                        .frame(minHeight: 110)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                        .accessibilityIdentifier("local-task-criteria")
                    Text("\(criteriaCharacterCount) / 8,000 characters")
                        .font(.caption)
                        .foregroundStyle(criteriaCharacterCount <= 8_000 ? Color.secondary : Color.red)
                }
            }
            .padding(8)
        }

        if model.localTaskRequest.taskType == .implement {
            GroupBox("Delivery") {
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("Commit changes", isOn: $model.localTaskRequest.delivery.commit)
                        .disabled(true)
                    Toggle("Push branch", isOn: $model.localTaskRequest.delivery.push)
                        .disabled(!selectedProjectAllowsPush)
                        .onChange(of: model.localTaskRequest.delivery.push) { _, enabled in
                            if !enabled { model.localTaskRequest.delivery.draftPR = false }
                            model.localTaskPlan = nil
                        }
                    Toggle("Create Draft PR", isOn: $model.localTaskRequest.delivery.draftPR)
                        .disabled(!selectedProjectAllowsPR || !model.localTaskRequest.delivery.push)
                        .onChange(of: model.localTaskRequest.delivery.draftPR) { _, _ in
                            model.localTaskPlan = nil
                        }
                    Text("Delivery can only be reduced from the registered project policy. A canonical commit is required for the verification seal.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .padding(8)
            }
        }

        Text("Goal and criteria are sent as structured task content over stdin. They cannot set commands, argv, paths, environment variables, SQL, credentials, or sandbox policy.")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private var goalIsValid: Bool {
        let count = model.localTaskRequest.goal
            .trimmingCharacters(in: .whitespacesAndNewlines).count
        return (10...8_000).contains(count)
    }

    private var criteriaBinding: Binding<String> {
        Binding(
            get: { model.localTaskRequest.acceptanceCriteria.joined(separator: "\n") },
            set: { value in
                model.localTaskRequest.acceptanceCriteria = value
                    .components(separatedBy: .newlines)
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
                model.localTaskPlan = nil
            }
        )
    }

    private var criteriaCharacterCount: Int {
        model.localTaskRequest.acceptanceCriteria.reduce(0) { $0 + $1.count }
    }

    private var selectedProjectAllowsPush: Bool {
        model.projects.first(where: { $0.projectID == model.localTaskRequest.projectID })?
            .autoPush == true
    }

    private var selectedProjectAllowsPR: Bool {
        model.projects.first(where: { $0.projectID == model.localTaskRequest.projectID })?
            .autoPR == true
    }
}

private struct LocalTaskPlanView: View {
    let plan: LocalTaskPlan

    var body: some View {
        GroupBox("Execution snapshot") {
            VStack(alignment: .leading, spacing: 9) {
                LabeledContent("Project", value: plan.projectName)
                LabeledContent("Repository", value: plan.repositoryPath)
                LabeledContent("Base", value: "\(plan.defaultBranch) @ \(plan.baseSHA ?? String(localized: "Unavailable"))")
                LabeledContent("Task type", value: plan.taskType.title)
                LabeledContent("Goal", value: plan.goalSummary)
                LabeledContent(
                    "Execution profile",
                    value: "revision \(plan.executionProfileRevision) · \(plan.executionProfileSHA256)"
                )
                LabeledContent("Adapter", value: "\(plan.codexAdapter) · \(plan.codexExecutable)")
                LabeledContent("Worktree root", value: plan.worktreeRoot)
                LabeledContent("Commit", value: yesNo(plan.delivery.commit))
                LabeledContent("Push", value: yesNo(plan.delivery.push))
                LabeledContent("Draft PR", value: yesNo(plan.delivery.draftPR))
                LabeledContent("Plan expires", value: plan.expiresAt)
                LabeledContent("Plan token", value: plan.planToken)
            }
            .textSelection(.enabled)
            .padding(8)
        }

        if !plan.acceptanceCriteria.isEmpty {
            GroupBox("Acceptance criteria") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(plan.acceptanceCriteria.enumerated()), id: \.offset) {
                        Text("\($0.offset + 1). \($0.element)")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(8)
            }
        }

        if !plan.verification.isEmpty {
            GroupBox("Verification commands") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(plan.verification) { verification in
                        Label(
                            verification.description,
                            systemImage: verification.alwaysRun
                                ? "checkmark.seal" : "checkmark.circle"
                        )
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(8)
            }
        }

        GroupBox("Readiness") {
            VStack(alignment: .leading, spacing: 8) {
                Label(
                    plan.readiness.ready ? "Ready to create" : "Resolve blockers before creating",
                    systemImage: plan.readiness.ready
                        ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
                )
                .foregroundStyle(plan.readiness.ready ? .green : .orange)
                ForEach(plan.readiness.blockers) { blocker in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(blocker.name).font(.headline)
                        Text(blocker.detail).foregroundStyle(.secondary)
                        Text(blocker.nextAction).font(.caption)
                    }
                }
                Text("External ChatGPT acceptance remains Pending and is not required for this local task.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }

    private func short(_ value: String?) -> String {
        value.map { String($0.prefix(12)) } ?? String(localized: "Unavailable")
    }

    private func yesNo(_ value: Bool) -> String {
        value ? String(localized: "Yes") : String(localized: "No")
    }
}

private struct LocalTaskInlineIssue: View {
    let issue: UserFacingIssue
    @ObservedObject var model: AppModel

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                Label(issue.title, systemImage: "exclamationmark.triangle.fill")
                    .font(.headline).foregroundStyle(.orange)
                Text(issue.message).textSelection(.enabled)
                Text("Next: \(issue.nextAction)")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Review new plan") { model.reviewNewLocalTaskPlan() }
                    Button("Open Diagnostics") { model.openDiagnosticsFromLocalTask() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("local-task-inline-error")
    }
}
