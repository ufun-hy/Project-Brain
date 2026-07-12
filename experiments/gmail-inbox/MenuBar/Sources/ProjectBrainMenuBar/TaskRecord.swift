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
 func isStale(at now:Date, threshold:TimeInterval=180)->Bool { guard state=="running",let value=lastHeartbeatAt,let d=ISO8601DateFormatter().date(from:value) else{return false}; return now.timeIntervalSince(d)>threshold }
 func duration(at now:Date=Date())->TimeInterval? { guard let value=startedAt,let start=ISO8601DateFormatter().date(from:value) else{return nil}; if state=="running" {return max(0,now.timeIntervalSince(start))}; guard let value=finishedAt ?? Optional(updatedAt),let end=ISO8601DateFormatter().date(from:value) else{return nil}; return max(0,end.timeIntervalSince(start)) }
}

enum TaskSummary {
 static let active:Set<String>=["running","awaiting_review"]
 static func latestRelevant(_ tasks:[TaskRecord])->[TaskRecord] {
  let grouped=Dictionary(grouping:tasks,by:{$0.project})
  return grouped.values.compactMap{$0.max(by:{$0.updatedAt<$1.updatedAt})}.sorted{$0.updatedAt>$1.updatedAt}
 }
 static func icon(_ tasks:[TaskRecord],now:Date=Date())->String {
  let latest=latestRelevant(tasks)
  if latest.contains(where:{$0.isStale(at:now)}) {return "exclamationmark.circle.fill"}
  if latest.contains(where:{$0.state=="running"}) {return "bolt.circle.fill"}
  if latest.contains(where:{$0.state=="awaiting_review"}) {return "eye.circle.fill"}
  return "brain.head.profile"
 }
 static func idle(_ tasks:[TaskRecord])->Bool {!tasks.contains(where:{active.contains($0.state)})}
}
