package bench;

import static org.junit.jupiter.api.Assertions.*;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

class HttpMetricsTest {
  @Test
  void concurrentCompletionsRetainErrorsAndHistogramBoundaryCounts() throws Exception {
    var metrics = new HttpMetrics();
    var pool = Executors.newFixedThreadPool(8);
    for (int i = 0; i < 1000; i++) {
      final int number = i;
      pool.submit(() -> { metrics.received(); metrics.completed(number % 10 == 0 ? 503 : 200, 6000); });
    }
    pool.shutdown();
    assertTrue(pool.awaitTermination(10, TimeUnit.SECONDS));
    String text = metrics.exposition();
    assertTrue(text.contains("wiremock_http_completed_total 1000\n"));
    assertTrue(text.contains("wiremock_http_errors_total 100\n"));
    assertTrue(text.contains("wiremock_http_in_flight 0\n"));
    assertTrue(text.contains("wiremock_http_duration_seconds_bucket{le=\"5.0\"} 0\n"));
    assertTrue(text.contains("wiremock_http_duration_seconds_bucket{le=\"6.0\"} 1000\n"));
    assertTrue(text.contains("wiremock_http_duration_seconds_count 1000\n"));
    assertTrue(text.contains("wiremock_http_duration_seconds_sum 6000.0\n"));
  }

  @Test
  void absentTimingIsVisibleAndNeverRecordedAsZeroLatency() {
    var metrics = new HttpMetrics();
    metrics.received();
    metrics.completed(200, null);
    assertTrue(metrics.exposition().contains("wiremock_http_completed_total 1\n"));
    assertTrue(metrics.exposition().contains("wiremock_http_timing_missing_total 1\n"));
    assertTrue(metrics.exposition().contains("wiremock_http_duration_seconds_count 0\n"));
  }
}
