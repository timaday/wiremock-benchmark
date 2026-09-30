package bench;

import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

/**
 * Responsibility: aggregate monotonic elapsed durations for capture diagnostics.
 * Must not: decide success, retain event identities, or perform IO.
 * Contract: docs/CONTRACT.md, capture diagnostics (seconds).
 */
final class DurationMetric {
  private final LongAdder count = new LongAdder();
  private final LongAdder nanos = new LongAdder();
  private final AtomicLong maximum = new AtomicLong();

  void record(long elapsed) {
    if (elapsed < 0) throw new IllegalArgumentException("Elapsed duration must not be negative");
    nanos.add(elapsed);
    maximum.accumulateAndGet(elapsed, Math::max);
    count.increment();
  }

  Map<String, Number> snapshot() {
    return Map.of("count", count.sum(), "seconds", nanos.sum()/1e9, "maxSeconds", maximum.get()/1e9);
  }

  void expose(StringBuilder output, String name) {
    HttpMetrics.metric(output, name + "_count", "counter", count.sum());
    HttpMetrics.metric(output, name + "_seconds_total", "counter", nanos.sum()/1e9);
    HttpMetrics.metric(output, name + "_seconds_max", "gauge", maximum.get()/1e9);
  }
}
