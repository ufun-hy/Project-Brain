import Foundation
struct Acceptance: Codable { let satisfied:Int; let total:Int? }
struct TaskRecord: Codable, Identifiable {
 let schemaVersion:Int; let taskId:String; let project:String; let title:String; let state:String; let currentAction:String
 let createdAt:String; let startedAt:String?; let updatedAt:String; let finishedAt:String?; let lastHeartbeatAt:String?
 let attempt:Int; let branch:String?; let commit:String?; let prUrl:String?; let error:String?; let blockedReason:String?
 let evidenceSummary:String; let acceptance:Acceptance; let testSummary:String; let logPath:String?
 var id:String { taskId }
 enum CodingKeys:String,CodingKey { case schemaVersion="schema_version",taskId="task_id",project,title,state,currentAction="current_action",createdAt="created_at",startedAt="started_at",updatedAt="updated_at",finishedAt="finished_at",lastHeartbeatAt="last_heartbeat_at",attempt,branch,commit,prUrl="pr_url",error,blockedReason="blocked_reason",evidenceSummary="evidence_summary",acceptance,testSummary="test_summary",logPath="log_path" }
 var stale:Bool { guard state=="running",let value=lastHeartbeatAt,let d=ISO8601DateFormatter().date(from:value) else{return false}; return Date().timeIntervalSince(d)>180 }
}
