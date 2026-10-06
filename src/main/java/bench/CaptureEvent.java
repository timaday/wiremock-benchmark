package bench;

import java.util.Map;

/**
 * Responsibility: define the versioned full-body capture envelope.
 * Must not: infer identity or transform body bytes. Contract: docs/CONTRACT.md, envelope version 2.
 */
public record CaptureEvent(
    int schemaVersion,
    String eventId,
    String runId,
    String requestId,
    String correlationId,
    CorrelationStatus correlationStatus,
    Phase phase,
    long timestampMs,
    String method,
    String url,
    int status,
    Map<String, java.util.List<String>> headers,
    String bodyBase64) {
  public static final int SCHEMA_VERSION = 2;

  public CaptureEvent {
    if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported capture schema version");
    if (correlationId == null || correlationStatus == null)
      throw new IllegalArgumentException("Capture correlation metadata is required");
    if ((correlationStatus == CorrelationStatus.PRESENT) == correlationId.isBlank())
      throw new IllegalArgumentException("Capture correlation value/status mismatch");
    if (correlationStatus != CorrelationStatus.PRESENT && !correlationId.isEmpty())
      throw new IllegalArgumentException("Uncorrelated capture must have an empty correlation value");
  }
}
