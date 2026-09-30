package bench;

import java.util.concurrent.atomic.DoubleAdder;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

/**
 * Responsibility: aggregate benchmark HTTP lifecycle counters and server timing.
 * Must not: retain request identities, perform capture IO, or decide benchmark success.
 * Contract: docs/PORTAINER.md, telemetry contract.
 */
final class HttpMetrics {
  private static final double[] BOUNDS = {
    .01, .1, .5, 1, 1.5, 2, 3, 4, 5, 6, 6.025, 6.05, 6.1, 6.2, 6.5, 7, 8, 10, 15, 30
  };
  private final LongAdder received = new LongAdder();
  private final AtomicLong inFlight = new AtomicLong();
  private final LongAdder completed = new LongAdder();
  private final LongAdder errors = new LongAdder();
  private final LongAdder missingTiming = new LongAdder();
  private final LongAdder timed = new LongAdder();
  private final DoubleAdder duration = new DoubleAdder();
  private final LongAdder[] buckets = new LongAdder[BOUNDS.length];

  HttpMetrics() {
    for (int i = 0; i < buckets.length; i++) buckets[i] = new LongAdder();
  }

  void received() { inFlight.incrementAndGet(); received.increment(); }

  void completed(int status, Integer milliseconds) {
    completed.increment();
    inFlight.decrementAndGet();
    if (status < 200 || status >= 300) errors.increment();
    if (milliseconds == null || milliseconds < 0) {
      missingTiming.increment();
      return;
    }
    double seconds = milliseconds / 1000.0;
    duration.add(seconds);
    timed.increment();
    for (int i = 0; i < buckets.length; i++)
      if (seconds <= BOUNDS[i]) buckets[i].increment();
  }

  String exposition() {
    var out = new StringBuilder();
    metric(out, "wiremock_http_received_total", "counter", received.sum());
    metric(out, "wiremock_http_completed_total", "counter", completed.sum());
    metric(out, "wiremock_http_errors_total", "counter", errors.sum());
    metric(out, "wiremock_http_in_flight", "gauge", inFlight.get());
    metric(out, "wiremock_http_timing_missing_total", "counter", missingTiming.sum());
    out.append("# TYPE wiremock_http_duration_seconds histogram\n");
    for (int i = 0; i < buckets.length; i++)
      out.append("wiremock_http_duration_seconds_bucket{le=\"").append(BOUNDS[i])
          .append("\"} ").append(buckets[i].sum()).append('\n');
    out.append("wiremock_http_duration_seconds_bucket{le=\"+Inf\"} ").append(timed.sum()).append('\n');
    out.append("wiremock_http_duration_seconds_count ").append(timed.sum()).append('\n');
    out.append("wiremock_http_duration_seconds_sum ").append(duration.sum()).append('\n');
    return out.toString();
  }

  static void metric(StringBuilder out, String name, String type, Number value) {
    out.append("# TYPE ").append(name).append(' ').append(type).append('\n');
    out.append(name).append(' ').append(value).append('\n');
  }
}
