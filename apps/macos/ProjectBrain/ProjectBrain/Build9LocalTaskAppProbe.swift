import Foundation
import ProjectBrainKit

/// Final-bundle CI probe for the same typed App/Core adapter used by New Task.
/// It is unavailable outside an explicitly isolated CI environment.
enum Build9LocalTaskAppProbe {
    static func runIfRequested() -> Never? {
        let environment = ProcessInfo.processInfo.environment
        guard environment["CI"] == "true",
              environment["PROJECT_BRAIN_BUILD9_APP_PROBE"] == "1" else {
            return nil
        }
        let status: Int32
        do {
            try run(environment: environment)
            status = EXIT_SUCCESS
        } catch {
            if let output = environment["PROJECT_BRAIN_BUILD9_PROBE_OUTPUT"] {
                let failure: [String: Any] = [
                    "status": "error",
                    "error": SecretRedactor.redact(error.localizedDescription),
                ]
                try? write(failure, to: URL(filePath: output))
            }
            status = EXIT_FAILURE
        }
        fflush(nil)
        Darwin._exit(status)
    }

    private static func run(environment: [String: String]) throws {
        guard let runtimePath = environment["PROJECT_BRAIN_RUNTIME_ROOT"],
              let outputPath = environment["PROJECT_BRAIN_BUILD9_PROBE_OUTPUT"],
              let helper = Bundle.main.url(forResource: "project-brain", withExtension: nil),
              let contractURL = Bundle.main.url(
                forResource: "project-brain-cli-contract",
                withExtension: "json"
              ) else {
            throw CoreClientError.invalidInstallation(
                "Build 9 App probe is missing an isolated runtime, output, helper, or contract."
            )
        }
        let contract = try CoreCLIContractDocument(contentsOf: contractURL).contract
        let client = try CoreClient(
            executable: helper,
            runtimeRoot: URL(filePath: runtimePath),
            cliContract: contract
        )
        let mode = environment["PROJECT_BRAIN_BUILD9_PROBE_MODE"] ?? "create"
        if mode == "read" {
            guard let taskID = environment["PROJECT_BRAIN_BUILD9_PROBE_TASK_ID"] else {
                throw CoreClientError.invalidResponse("Build 9 read probe requires a task ID.")
            }
            let task = try client.task(taskID)
            try write([
                "status": "read",
                "helper_invocations": 1,
                "task": try jsonObject(task),
            ], to: URL(filePath: outputPath))
            return
        }
        guard mode == "create",
              let requestPath = environment["PROJECT_BRAIN_BUILD9_PROBE_REQUEST"] else {
            throw CoreClientError.invalidResponse("Build 9 create probe requires a request.")
        }

        let openStarted = ContinuousClock.now
        var request = try JSONDecoder().decode(
            LocalTaskRequest.self,
            from: Data(contentsOf: URL(filePath: requestPath))
        )
        let openSheetMS = elapsedMilliseconds(since: openStarted)
        var phases = [LocalTaskOperationPhase.idle.rawValue]

        let planFeedbackStarted = ContinuousClock.now
        phases.append(LocalTaskOperationPhase.buildingPlan.rawValue)
        let planFeedbackMS = elapsedMilliseconds(since: planFeedbackStarted)
        let planStarted = ContinuousClock.now
        let planned = try client.planLocalTask(request)
        let planWallMS = elapsedMilliseconds(since: planStarted)
        phases.append(LocalTaskOperationPhase.idle.rawValue)

        // Deliberately mutate the client-side form after planning. Confirmation
        // below remains token/hash-only and must create the reviewed canonical goal.
        request.goal = "This post-plan client mutation must not reach Core."
        request.acceptanceCriteria = []

        let createFeedbackStarted = ContinuousClock.now
        phases.append(LocalTaskOperationPhase.creatingTask.rawValue)
        let createFeedbackMS = elapsedMilliseconds(since: createFeedbackStarted)
        let createStarted = ContinuousClock.now
        let created = try client.createLocalTask(
            planToken: planned.plan.planToken,
            expectedPlanHash: planned.plan.planHash
        )
        let createWallMS = elapsedMilliseconds(since: createStarted)
        let postCreateUIStarted = ContinuousClock.now
        phases.append(LocalTaskOperationPhase.openingTask.rawValue)
        let immediateDetail = TaskDetail(summary: created.summary)
        guard immediateDetail.taskID == created.summary.taskID,
              immediateDetail.status == created.summary.status else {
            throw CoreClientError.invalidResponse(
                "Build 9 immediate task placeholder did not match the create response."
            )
        }
        phases.append(LocalTaskOperationPhase.idle.rawValue)
        let postCreateUIUpdateMS = elapsedMilliseconds(since: postCreateUIStarted)
        Thread.sleep(forTimeInterval: Double(created.nextRefreshAfterMS) / 1_000)
        let backgroundStarted = ContinuousClock.now
        let refreshed = try client.task(created.summary.taskID)
        let backgroundRefreshMS = elapsedMilliseconds(since: backgroundStarted)

        let evidence: [String: Any] = [
            "status": "created",
            "interactive_helper_invocations": 2,
            "background_helper_invocations": 1,
            "phases": phases,
            "canonical_goal": planned.plan.canonicalGoal,
            "summary": try jsonObject(created.summary),
            "project": try jsonObject(created.project),
            "creation_evidence": try jsonObject(created.creationEvidence),
            "next_refresh_after_ms": created.nextRefreshAfterMS,
            "timing_ms": [
                "open_sheet": openSheetMS,
                "plan_click_feedback": planFeedbackMS,
                "create_click_feedback": createFeedbackMS,
                "plan_wall": planWallMS,
                "create_wall": createWallMS,
                "post_create_ui_update": postCreateUIUpdateMS,
                "background_snapshot_refresh": backgroundRefreshMS,
                "plan_core": planned.timingMS,
                "create_core": created.timingMS,
            ],
            "background_task_status": refreshed.status.rawValue,
        ]
        try write(evidence, to: URL(filePath: outputPath))
    }

    private static func jsonObject<T: Encodable>(_ value: T) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
    }

    private static func write(_ value: [String: Any], to url: URL) throws {
        let data = try JSONSerialization.data(
            withJSONObject: value,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        )
        try data.write(to: url, options: .atomic)
    }

    private static func elapsedMilliseconds(
        since started: ContinuousClock.Instant
    ) -> Double {
        let duration = started.duration(to: .now)
        return Double(duration.components.seconds) * 1_000
            + Double(duration.components.attoseconds) / 1_000_000_000_000_000
    }
}
