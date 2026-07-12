import XCTest
@testable import ProjectBrainMenuBar
final class TaskRecordTests:XCTestCase {
 func record(_ id:String,_ project:String,_ state:String,_ updated:String="2026-01-01T00:00:00Z",_ heartbeat:String?=nil,_ finished:String?=nil)->TaskRecord { TaskRecord(schemaVersion:1,taskId:id,project:project,title:"T",state:state,currentAction:"A",createdAt:"2026-01-01T00:00:00Z",startedAt:"2026-01-01T00:00:00Z",updatedAt:updated,finishedAt:finished,lastHeartbeatAt:heartbeat,attempt:1,branch:nil,commit:nil,prUrl:nil,error:nil,blockedReason:nil,evidenceSummary:"",acceptance:Acceptance(satisfied:1,total:2),testSummary:"1/1 passed",logPath:nil) }
 func testLatestPerProjectObsoletesOldFailure(){let tasks=[record("old","P","failed"),record("new","P","accepted","2026-02-01T00:00:00Z")]; XCTAssertEqual(TaskSummary.latestRelevant(tasks).map(\.taskId),["new"]); XCTAssertEqual(TaskSummary.icon(tasks),"brain.head.profile")}
 func testStaleAndRunningIcon(){let now=ISO8601DateFormatter().date(from:"2026-01-01T00:10:00Z")!; let task=record("m","P","running","2026-01-01T00:00:00Z","2026-01-01T00:00:00Z"); XCTAssertTrue(task.isStale(at:now)); XCTAssertEqual(TaskSummary.icon([task],now:now),"exclamationmark.circle.fill")}
 func testFixedFinishedDuration(){let task=record("m","P","accepted","2026-01-01T00:01:00Z",nil,"2026-01-01T00:01:00Z"); XCTAssertEqual(task.duration(at:Date(timeIntervalSince1970:9999999999)),60)}
 func testIdleRetainsHistory(){XCTAssertTrue(TaskSummary.idle([record("m","P","failed")])); XCTAssertFalse(TaskSummary.idle([record("m","P","awaiting_review")]))}
}
