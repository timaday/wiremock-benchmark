package bench;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Responsibility: project capture-stage counters into JSON and Prometheus diagnostics.
 * Must not: collect new timings, query SQLite, or change capture lifecycle.
 * Contract: docs/CONTRACT.md, capture diagnostics.
 */
final class CaptureDiagnostics {
  private final boolean enabled;
  private final DurableOutbox outbox;
  private final Map<String, DurationMetric> durations;

  CaptureDiagnostics(boolean enabled, DurableOutbox outbox, RabbitPublisher publisher) {
    this.enabled = enabled;
    this.outbox = outbox;
    durations = new LinkedHashMap<>();
    durations.put("append_wait", enabled ? outbox.appendWait : new DurationMetric());
    durations.put("transaction", enabled ? outbox.transactions : new DurationMetric());
    durations.put("read", enabled ? publisher.reads : new DurationMetric());
    durations.put("publish_confirm", enabled ? publisher.publishConfirms : new DurationMetric());
    durations.put("delete", enabled ? publisher.deletions : new DurationMetric());
  }

  Map<String, Object> snapshot() {
    var result = new LinkedHashMap<String, Object>();
    result.put("queuedOperations", enabled ? outbox.queued() : 0);
    result.put("committedBytes", enabled ? outbox.committedBytes.get() : 0L);
    result.put("maximumAppendBatch", enabled ? outbox.maximumAppendBatch.get() : 0L);
    durations.forEach((name, metric) -> result.put(name, metric.snapshot()));
    return result;
  }

  void expose(StringBuilder output) {
    HttpMetrics.metric(output, "wiremock_capture_queued_operations", "gauge", enabled ? outbox.queued() : 0);
    HttpMetrics.metric(output, "wiremock_capture_committed_bytes_total", "counter", enabled ? outbox.committedBytes.get() : 0);
    HttpMetrics.metric(output, "wiremock_capture_append_batch_max", "gauge", enabled ? outbox.maximumAppendBatch.get() : 0);
    durations.forEach((name, metric) -> metric.expose(output, "wiremock_capture_" + name));
  }
}
