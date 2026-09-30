package bench;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class DurationMetricTest {
  @Test
  void reportsSecondsCountAndMaximumWithoutChangingOnRead() {
    var metric = new DurationMetric();
    metric.record(500_000_000L);
    metric.record(250_000_000L);
    assertEquals(2L, metric.snapshot().get("count"));
    assertEquals(0.75, metric.snapshot().get("seconds"));
    assertEquals(0.5, metric.snapshot().get("maxSeconds"));
    var text = new StringBuilder();
    metric.expose(text, "probe");
    assertTrue(text.toString().contains("probe_seconds_total 0.75"));
    assertEquals(2L, metric.snapshot().get("count"));
    assertThrows(IllegalArgumentException.class, () -> metric.record(-1));
  }
}
