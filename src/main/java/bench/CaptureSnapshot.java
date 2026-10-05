package bench;

import java.util.Map;

/**
 * Responsibility: carry a read-only projection of the selected capture sink.
 * Must not: infer delivery or reconciliation from counters.
 * Contract: docs/CONTRACT.md, capture diagnostics.
 */
record CaptureSnapshot(CaptureMode mode, long pending, long committed, long confirmed,
    boolean brokerConnected, long reconnects, Map<String, Object> diagnostics) {}
