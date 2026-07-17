import Foundation

public protocol ObservationClock: Sendable {
    func sleep(for seconds: TimeInterval) async throws
}

public struct SystemObservationClock: ObservationClock {
    public init() {}

    public func sleep(for seconds: TimeInterval) async throws {
        try await Task.sleep(nanoseconds: UInt64(max(0, seconds) * 1_000_000_000))
    }
}

public struct StateObservationPolicy: Equatable, Sendable {
    public let foregroundInterval: TimeInterval
    public let backgroundInterval: TimeInterval
    public let offlineInterval: TimeInterval
    public let failureBaseInterval: TimeInterval
    public let maximumBackoff: TimeInterval

    public init(
        foregroundInterval: TimeInterval = 3,
        backgroundInterval: TimeInterval = 15,
        offlineInterval: TimeInterval = 20,
        failureBaseInterval: TimeInterval = 6,
        maximumBackoff: TimeInterval = 60
    ) {
        self.foregroundInterval = foregroundInterval
        self.backgroundInterval = backgroundInterval
        self.offlineInterval = offlineInterval
        self.failureBaseInterval = failureBaseInterval
        self.maximumBackoff = maximumBackoff
    }

    public func delay(isForeground: Bool, serviceOnline: Bool, failures: Int) -> TimeInterval {
        let normal = isForeground ? foregroundInterval : backgroundInterval
        if failures > 0 {
            let exponent = min(failures - 1, 10)
            let backoff = min(maximumBackoff, failureBaseInterval * pow(2, Double(exponent)))
            return serviceOnline ? backoff : max(offlineInterval, backoff)
        }
        return serviceOnline ? normal : max(normal, offlineInterval)
    }
}

public struct ObservationUpdate<Value: Sendable>: Sendable {
    public let value: Value
    public let serviceOnline: Bool

    public init(value: Value, serviceOnline: Bool) {
        self.value = value
        self.serviceOnline = serviceOnline
    }
}

public actor StateObservationLoop<Value: Sendable> {
    public typealias Selection = @Sendable () async -> String?
    public typealias Refresh = @Sendable (String?) async throws -> ObservationUpdate<Value>
    public typealias Consume = @MainActor @Sendable (Value) -> Void

    private let policy: StateObservationPolicy
    private let clock: any ObservationClock
    private var task: Task<Void, Never>?
    private var generation: UUID?
    private var isForeground = true

    public init(
        policy: StateObservationPolicy = StateObservationPolicy(),
        clock: any ObservationClock = SystemObservationClock()
    ) {
        self.policy = policy
        self.clock = clock
    }

    public func start(
        selection: @escaping Selection,
        refresh: @escaping Refresh,
        consume: @escaping Consume
    ) {
        guard task == nil else { return }
        let runID = UUID()
        generation = runID
        task = Task { [weak self] in
            var failures = 0
            var serviceOnline = true
            while !Task.isCancelled {
                do {
                    let update = try await refresh(await selection())
                    serviceOnline = update.serviceOnline
                    failures = 0
                    await consume(update.value)
                } catch is CancellationError {
                    break
                } catch {
                    failures += 1
                }
                guard let self, !Task.isCancelled else { break }
                let foreground = await self.foregroundState()
                let delay = policy.delay(
                    isForeground: foreground,
                    serviceOnline: serviceOnline,
                    failures: failures
                )
                do {
                    try await clock.sleep(for: delay)
                } catch {
                    break
                }
            }
            await self?.finished(runID: runID)
        }
    }

    public func setForeground(_ value: Bool) { isForeground = value }

    public func cancel() {
        task?.cancel()
        task = nil
        generation = nil
    }

    public var isRunning: Bool { task != nil }

    private func foregroundState() -> Bool { isForeground }
    private func finished(runID: UUID) {
        guard generation == runID else { return }
        task = nil
        generation = nil
    }
}
