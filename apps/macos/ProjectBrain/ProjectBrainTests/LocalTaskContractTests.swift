import Foundation
import XCTest
@testable import ProjectBrainKit

final class LocalTaskContractTests: XCTestCase {
    private let exactGoal = "分析当前项目的 README 和代码目录，说明项目用途、主要模块和当前风险。不要修改任何文件。"

    private var projectRoot: URL {
        var root = URL(filePath: #filePath)
        for _ in 0..<2 { root.deleteLastPathComponent() }
        return root
    }

    func testPlanCommandFreezesExactChineseRequestBeforeClientMutation() throws {
        var request = LocalTaskRequest(projectID: "project-brain", goal: exactGoal)
        let command = CoreCommand.localTaskPlan(request)
        request.goal = "Changed after planning"
        let input = try XCTUnwrap(command.standardInput())
        let decoded = try JSONDecoder().decode(LocalTaskRequest.self, from: input)
        XCTAssertEqual(decoded.goal, exactGoal)
        XCTAssertNotEqual(decoded.goal, request.goal)
    }

    func testConfirmationContainsOnlyOpaqueTokenAndExpectedPlanHash() throws {
        let token = "local-v2:opaque"
        let hash = String(repeating: "a", count: 64)
        let command = CoreCommand.localTaskCreate(.init(
            planToken: token,
            expectedPlanHash: hash
        ))
        let input = try XCTUnwrap(command.standardInput())
        let value = try XCTUnwrap(
            JSONSerialization.jsonObject(with: input) as? [String: String]
        )
        XCTAssertEqual(value, ["plan_token": token, "expected_plan_hash": hash])
        XCTAssertNil(value["goal"])
        XCTAssertNil(value["project_id"])
        XCTAssertNil(value["delivery"])
    }

    func testOperationPhasesExposeImmediateFeedbackAndSafeCancellation() {
        XCTAssertTrue(LocalTaskOperationPhase.buildingPlan.isBusy)
        XCTAssertTrue(LocalTaskOperationPhase.buildingPlan.canCancel)
        XCTAssertTrue(LocalTaskOperationPhase.creatingTask.isBusy)
        XCTAssertFalse(LocalTaskOperationPhase.creatingTask.canCancel)
        XCTAssertTrue(LocalTaskOperationPhase.openingTask.isBusy)
        XCTAssertFalse(LocalTaskOperationPhase.failed.isBusy)
    }

    func testCreateSummaryMakesImmediatePendingTaskPlaceholder() {
        let summary = TaskSummary(
            taskID: "task-1",
            projectID: "project-brain",
            project: "Project-Brain",
            goal: exactGoal,
            sourceType: "local_app",
            localTaskType: .analysis,
            status: .pending
        )
        let detail = TaskDetail(summary: summary)
        XCTAssertEqual(detail.taskID, summary.taskID)
        XCTAssertEqual(detail.goal, exactGoal)
        XCTAssertEqual(detail.status, .pending)
        XCTAssertTrue(detail.events.isEmpty)
        XCTAssertTrue(detail.verification.isEmpty)
    }

    func testEnglishAndSimplifiedChineseRecoveryCopyIsPackaged() throws {
        let resourceRoot = projectRoot.appending(path: "ProjectBrain/Resources")
        let english = try String(contentsOf: resourceRoot.appending(
            path: "en.lproj/Localizable.strings"
        ))
        let chinese = try String(contentsOf: resourceRoot.appending(
            path: "zh-Hans.lproj/Localizable.strings"
        ))
        XCTAssertTrue(english.contains(#""Check the task goal" = "Check the task goal";"#))
        XCTAssertTrue(chinese.contains(#""Check the task goal" = "请检查任务目标";"#))
        XCTAssertTrue(chinese.contains(#""Execution plan changed" = "执行计划已变化";"#))
        XCTAssertTrue(chinese.contains(#""Edit the goal, then review a new plan.""#))
        XCTAssertTrue(chinese.contains(#""Next" = "下一步";"#))
    }

    func testCreateGuardPreventsDuplicateSubmitAndDefersOneDetailRefresh() throws {
        let appModel = try String(contentsOf: projectRoot.appending(
            path: "ProjectBrain/AppModel.swift"
        ))
        let create = try XCTUnwrap(appModel.components(
            separatedBy: "func createLocalTask()"
        ).last?.components(separatedBy: "func cancelLocalTaskSheet()").first)
        XCTAssertTrue(create.contains("!localTaskPhase.isBusy"))
        XCTAssertTrue(create.contains("localTaskPhase = .creatingTask"))
        XCTAssertTrue(create.contains("isNewTaskPresented = false"))
        XCTAssertTrue(create.contains("schedulePostCreateRefresh("))
        XCTAssertFalse(create.contains("backend.refresh"))

        let refresh = try XCTUnwrap(appModel.components(
            separatedBy: "func schedulePostCreateRefresh"
        ).last)
        XCTAssertEqual(refresh.components(separatedBy: "backend.task(taskID)").count - 1, 1)
        XCTAssertFalse(refresh.contains("backend.refresh"))
    }

    func testGoalErrorFocusAndTechnicalDetailsHideReplayToken() throws {
        let source = try String(contentsOf: projectRoot.appending(
            path: "ProjectBrain/NewTaskView.swift"
        ))
        XCTAssertTrue(source.contains("@FocusState private var focusedField"))
        XCTAssertTrue(source.contains("model.localTaskIssue?.field == \"goal\""))
        XCTAssertTrue(source.contains("DisclosureGroup(\"Technical details\""))
        XCTAssertTrue(source.contains("Plan fingerprint"))
        XCTAssertFalse(source.contains("plan.planToken"))
    }

    func testPlanFormDoesNotUseSwiftCharacterCountAsSubmitAuthority() throws {
        let source = try String(contentsOf: projectRoot.appending(
            path: "ProjectBrain/NewTaskView.swift"
        ))
        XCTAssertTrue(source.contains("unicodeScalars.count"))
        XCTAssertFalse(source.contains("canonicalGoal.count"))
        XCTAssertFalse(source.contains("goal.count >="))
    }
}
