package bench;

import java.util.Map;

/** One immutable capture envelope; body is complete base64, never a preview. */
public record CaptureEvent(
    String eventId,
    String runId,
    String requestId,
    Phase phase,
    long timestampMs,
    String method,
    String url,
    int status,
    Map<String, java.util.List<String>> headers,
    String bodyBase64) {}
