package bench;

/**
 * Responsibility: retain one immutable per-exchange identity snapshot.
 * Must not: reread a live mapping or request body. Contract: docs/CONTRACT.md.
 */
public record CaptureIdentity(String runId, String requestId, String correlationId,
                              CorrelationStatus correlationStatus) {}
