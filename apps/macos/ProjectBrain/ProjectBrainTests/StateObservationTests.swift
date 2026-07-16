import Foundation
import XCTest
@testable import ProjectBrainKit

private actor RecordingObservationClock: ObservationClock {
    private(set) var delays: [TimeInterval] = []

    func sleep(for seconds: TimeInterval) async throws {
        delays.append(seconds)
        try await Task.sleep(nanoseconds: 1_000_000)
    }

    func snapshot() -> [TimeInterval] { delays }
}

private final class ObservationProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var calls = 0
    private var active = 0
    private(set) var maximumActive = 0
    private(set) var selections: [String?] = []
    private(set) var consumed: [Int] = []

    func begin(selection: String?) -> Int {
        lock.lock()
        defer { lock.unlock() }
        calls += 1
        active += 1
        maximumActive = max(maximumActive, active)
        selections.append(selection)
        return calls
    }

    func end() {
        lock.lock()
        active -= 1
        lock.unlock()
    }

    func consume(_ value: Int) {
        lock.lock()
        consumed.append(value)
        lock.unlock()
    }

    func callCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return calls
    }

    func snapshot() -> (Int, [String?], [Int]) {
        lock.lock()
        defer { lock.unlock() }
        return (maximumActive, selections, consumed)
    }
}

final class StateObservationTests: XCTestCase {
    func testAutomaticRefreshIsImmediateSequentialAndRefreshesSelectedDetail() async throws {
        let clock = RecordingObservationClock()
        let probe = ObservationProbe()
        let loop = StateObservationLoop<Int>(clock: clock)
        await loop.start(
            selection: { "task-7" },
            refresh: { selection in
                let call = probe.begin(selection: selection)
                defer { probe.end() }
                try await Task.sleep(nanoseconds: 5_000_000)
                return ObservationUpdate(value: call, serviceOnline: true)
            },
            consume: { probe.consume($0) }
        )
        try await waitUntil { probe.callCount() >= 3 }
        await loop.cancel()
        let snapshot = probe.snapshot()
        XCTAssertEqual(snapshot.0, 1)
        XCTAssertTrue(snapshot.1.prefix(3).allSatisfy { $0 == "task-7" })
        XCTAssertGreaterThanOrEqual(snapshot.2.count, 2)
    }

    func testFailuresBackOffAndCancellationStopsFurtherRefreshes() async throws {
        let clock = RecordingObservationClock()
        let probe = ObservationProbe()
        let loop = StateObservationLoop<Int>(clock: clock)
        await loop.start(
            selection: { nil },
            refresh: { selection in
                let call = probe.begin(selection: selection)
                defer { probe.end() }
                if call <= 2 { throw URLError(.cannotConnectToHost) }
                return ObservationUpdate(value: call, serviceOnline: true)
            },
            consume: { probe.consume($0) }
        )
        try await waitUntil { await clock.snapshot().count >= 3 }
        let delays = await clock.snapshot()
        XCTAssertEqual(Array(delays.prefix(3)), [6, 12, 3])
        await loop.cancel()
        let stoppedAt = probe.callCount()
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertLessThanOrEqual(probe.callCount(), stoppedAt + 1)
        let running = await loop.isRunning
        XCTAssertFalse(running)
    }

    func testBackgroundAndOfflinePoliciesUseSlowerIntervals() {
        let policy = StateObservationPolicy()
        XCTAssertEqual(policy.delay(isForeground: true, serviceOnline: true, failures: 0), 3)
        XCTAssertEqual(policy.delay(isForeground: false, serviceOnline: true, failures: 0), 15)
        XCTAssertEqual(policy.delay(isForeground: true, serviceOnline: false, failures: 0), 20)
        XCTAssertEqual(policy.delay(isForeground: true, serviceOnline: false, failures: 1), 20)
        XCTAssertEqual(policy.delay(isForeground: true, serviceOnline: true, failures: 5), 60)
    }

    private func waitUntil(
        timeout: TimeInterval = 1,
        condition: @escaping () async -> Bool
    ) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await condition() { return }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTFail("Timed out waiting for observation")
    }
}
