import Foundation
import XCTest
@testable import ProjectBrainKit

final class CoreModelsTests: XCTestCase {
    func testStatusJSONDecodesPresenterModelAndVerificationPhase() throws {
        let data = Data(#"""
        {
          "status":"ok",
          "counts":{"running":1},
          "tasks":[{
            "task_id":"task-1","project_id":"project-1","project":"Example",
            "goal":"Ship product shell","status":"running","attempt_phase":"verification",
            "attempt_count":2,"created_at":"2026-07-16T00:00:00Z",
            "updated_at":"2026-07-16T00:01:00Z","elapsed_seconds":12,
            "branch":"codex/task-1","commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "pr_url":"https://github.com/example/repo/pull/1","last_error":null,
            "next_action":"Wait","project_config_revision":3,
            "project_config_sha256":"abcdef1234567890"
          }]
        }
        """#.utf8)
        let value = try JSONDecoder().decode(CoreStatusResponse.self, from: data)
        XCTAssertEqual(value.tasks.first?.presentedStatus, "Verifying")
        XCTAssertEqual(value.tasks.first?.projectConfigRevision, 3)
        XCTAssertEqual(value.counts["running"], 1)
    }

    func testEveryCoreTaskStatusHasAProductPresentation() {
        XCTAssertEqual(Set(TaskStatus.allCases.map(\.rawValue)).count, 15)
        XCTAssertTrue(TaskStatus.allCases.allSatisfy { !$0.title.isEmpty })
        XCTAssertEqual(TaskStatus.awaitingReview.title, "Needs review")
        XCTAssertEqual(TaskStatus.accepted.title, "Succeeded")
        XCTAssertEqual(TaskStatus.completed.title, "Completed")
    }

    func testMenuAggregationUsesPersistentTaskAndServiceState() {
        let running = TaskSummary(
            taskID: "one", projectID: "p", project: "P", status: .running
        )
        let service = ServiceStatusResponse(
            status: "healthy",
            helperExecutable: true,
            services: [
                ServiceItem(name: "worker", label: "worker", state: "running", installed: true, lastExitCode: nil),
                ServiceItem(name: "mcp", label: "mcp", state: "running", installed: true, lastExitCode: nil),
            ]
        )
        XCTAssertEqual(MenuBarSnapshot.make(tasks: [running], service: service).status, .running)

        let failed = TaskSummary(
            taskID: "two", projectID: "p", project: "P", status: .verificationFailed
        )
        XCTAssertEqual(MenuBarSnapshot.make(tasks: [failed], service: service).status, .needsAttention)
        XCTAssertEqual(MenuBarSnapshot.make(tasks: [], service: nil).status, .offline)
    }

    func testTaskDetailExtractsChangedFilesAndReliableEvidence() throws {
        let data = Data(#"""
        {
          "task_id":"task-1","project_id":"p","project":"P","goal":"Goal",
          "status":"awaiting_review","attempt_phase":"review","attempt_count":1,
          "branch":"codex/task-1","commit":"abc","head_sha":"abc","pr_url":null,
          "last_error":null,"next_action":"Review",
          "acceptance_criteria":[{"id":"tests","text":"Tests pass"}],
          "verification":[{"verification_id":1,"criterion_id":"tests","criterion_text":"Tests pass","status":"passed","evidence_summary":"175 tests","exit_code":0}],
          "reviews":[],
          "events":[{"event_id":1,"event_type":"execution_completed","payload":{"changed_files":["src/a.py","tests/test_a.py"]},"created_at":"2026-07-16T00:00:00Z"}]
        }
        """#.utf8)
        let detail = try JSONDecoder().decode(TaskDetail.self, from: data)
        XCTAssertEqual(detail.changedFiles, ["src/a.py", "tests/test_a.py"])
        XCTAssertEqual(detail.verification.first?.status, "passed")
        XCTAssertEqual(detail.acceptanceCriteria.first?.displayText, "Tests pass")
    }

    func testLocalTaskRequestEncodesOnlyTheStrictSourceNeutralSchema() throws {
        let request = LocalTaskRequest(
            projectID: "project-brain",
            taskType: .implement,
            goal: "Implement the reviewed local task flow.",
            acceptanceCriteria: ["Keep the main checkout unchanged"],
            delivery: .init(commit: true, push: false, draftPR: false)
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
                as? [String: Any]
        )
        XCTAssertEqual(Set(object.keys), [
            "schema_version", "source", "project_id", "task_type", "goal",
            "acceptance_criteria", "delivery",
        ])
        XCTAssertEqual(object["schema_version"] as? Int, 1)
        XCTAssertEqual(object["source"] as? String, "local_app")
        for forbidden in ["command", "argv", "cwd", "environment", "sql", "path"] {
            XCTAssertNil(object[forbidden])
        }
    }

    func testLocalAnalysisResultAndExecutionSnapshotDecodeForTaskCenter() throws {
        let data = Data(#"""
        {
          "task_id":"local-1","project_id":"p","project":"P","goal":"Review readiness",
          "source_type":"local_app","local_task_type":"analysis","status":"completed",
          "attempt_phase":"implementation","attempt_count":1,"branch":null,"commit":null,
          "head_sha":null,"pr_url":null,"last_error":null,"next_action":"Review result",
          "acceptance_criteria":[],"verification":[],"reviews":[],"events":[],
          "base_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "project_config_revision":4,"project_config_sha256":"bbbbbbbbbbbbbbbb",
          "delivery":{"commit":false,"push":false,"draft_pr":false},
          "result":{"schema_version":1,"kind":"analysis","summary":"Repository is ready","changed_files":[]}
        }
        """#.utf8)
        let detail = try JSONDecoder().decode(TaskDetail.self, from: data)
        XCTAssertEqual(detail.sourceType, "local_app")
        XCTAssertEqual(detail.localTaskType, .analysis)
        XCTAssertEqual(detail.status, .completed)
        XCTAssertEqual(detail.projectConfigRevision, 4)
        XCTAssertEqual(detail.result?["summary"]?.displayText, "Repository is ready")
        XCTAssertEqual(detail.delivery?.commit, false)
    }
}
