import AppKit
import ProjectBrainKit
import SwiftUI
import UniformTypeIdentifiers

struct ProjectsView: View {
    @ObservedObject var model: AppModel
    @State private var editingProject: ProjectSummary?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Projects").font(.largeTitle.bold())
                Spacer()
                Button("Add project…", action: chooseRepository)
                    .buttonStyle(.borderedProminent)
            }
            .padding(24)

            List(model.projects) { project in
                HStack(spacing: 16) {
                    Image(systemName: project.acceptingTasks ? "folder.fill.badge.checkmark" : "folder.badge.minus")
                        .font(.title2)
                        .foregroundStyle(project.acceptingTasks ? Color.accentColor : Color.secondary)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(project.name).font(.headline)
                        Text("\(project.projectID) · \(project.defaultBranch)")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("Config r\(project.configRevision ?? 0) · \(project.shortConfigHash ?? "unavailable")")
                            .font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Toggle("Auto-push", isOn: .constant(project.autoPush)).disabled(true)
                    Toggle("Draft PR", isOn: .constant(project.autoPR)).disabled(true)
                    Menu {
                        Button("Edit configuration…") { editingProject = project }
                        Button(project.acceptingTasks ? "Pause new tasks" : "Resume new tasks") {
                            model.planLifecycle(
                                projectID: project.projectID,
                                action: project.acceptingTasks ? .pause : .resume
                            )
                        }
                        Divider()
                        Button("Remove registration…", role: .destructive) {
                            model.planLifecycle(projectID: project.projectID, action: .remove)
                        }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
                .padding(.vertical, 7)
            }
            .overlay {
                if model.projects.isEmpty {
                    ContentUnavailableView(
                        "No registered projects",
                        systemImage: "folder.badge.plus",
                        description: Text("Add a validated Git repository to receive tasks.")
                    )
                }
            }
        }
        .sheet(item: $editingProject) { project in
            ProjectEditor(model: model, project: project)
        }
        .sheet(isPresented: Binding(
            get: { model.projectPlan != nil && model.projectDraft != nil && model.onboarding.completed },
            set: { if !$0 { model.projectPlan = nil; model.projectDraft = nil } }
        )) {
            if let plan = model.projectPlan?.plan {
                ConfirmationSheet(
                    title: "Add project",
                    actionTitle: "Apply configuration",
                    content: AnyView(PlanSummary(plan: plan)),
                    cancel: { model.projectPlan = nil; model.projectDraft = nil },
                    confirm: { model.applyNewProject() }
                )
            }
        }
        .sheet(isPresented: Binding(
            get: { model.lifecyclePlan != nil },
            set: { if !$0 { model.lifecyclePlan = nil } }
        )) {
            if let plan = model.lifecyclePlan {
                ConfirmationSheet(
                    title: plan.action.capitalized + " project",
                    actionTitle: "Confirm \(plan.action)",
                    content: AnyView(
                        VStack(alignment: .leading, spacing: 10) {
                            LabeledContent("Project", value: plan.projectID)
                            LabeledContent("Active tasks", value: String(plan.nonterminalTaskCount))
                            Label("Repository and task history will be preserved", systemImage: "checkmark.shield")
                        }
                    ),
                    cancel: { model.lifecyclePlan = nil },
                    confirm: { model.applyLifecycle() }
                )
            }
        }
    }

    private func chooseRepository() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.title = "Add a Git repository"
        if panel.runModal() == .OK, let url = panel.url { model.planNewProject(repository: url) }
    }
}

private struct ProjectEditor: View {
    @ObservedObject var model: AppModel
    let project: ProjectSummary
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var branch: String
    @State private var autoPush: Bool
    @State private var autoPR: Bool
    @State private var verificationFile: URL?

    init(model: AppModel, project: ProjectSummary) {
        self.model = model
        self.project = project
        _name = State(initialValue: project.name)
        _branch = State(initialValue: project.defaultBranch)
        _autoPush = State(initialValue: project.autoPush)
        _autoPR = State(initialValue: project.autoPR)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Edit \(project.name)").font(.title.bold())
            Form {
                TextField("Display name", text: $name)
                TextField("Default branch", text: $branch)
                Toggle("Auto-push verified commits", isOn: $autoPush)
                Toggle("Create Draft PR", isOn: $autoPR)
                LabeledContent("Trusted verification profile") {
                    Button(verificationFile?.lastPathComponent ?? "Choose JSON…", action: chooseVerification)
                }
            }
            if let plan = model.updatePlan?.plan {
                Divider()
                PlanSummary(plan: plan)
            }
            Spacer()
            HStack {
                Button("Cancel") { model.updatePlan = nil; dismiss() }
                Spacer()
                if model.updatePlan == nil {
                    Button("Review plan") {
                        model.planProjectUpdate(
                            project: project,
                            draft: ProjectUpdateDraft(
                                name: name,
                                defaultBranch: branch,
                                verificationFile: verificationFile,
                                autoPush: autoPush,
                                autoPR: autoPR
                            )
                        )
                    }.buttonStyle(.borderedProminent)
                } else {
                    Button("Apply plan") {
                        model.applyProjectUpdate(projectID: project.projectID)
                        dismiss()
                    }.buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(28)
        .frame(width: 600, height: 520)
    }

    private func chooseVerification() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        if panel.runModal() == .OK { verificationFile = panel.url }
    }
}

struct ConfirmationSheet: View {
    let title: String
    let actionTitle: String
    let content: AnyView
    let cancel: () -> Void
    let confirm: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text(title).font(.title.bold())
            content
            Spacer()
            HStack {
                Button("Cancel", action: cancel)
                Spacer()
                Button(actionTitle, action: confirm).buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(width: 580, height: 400)
    }
}
