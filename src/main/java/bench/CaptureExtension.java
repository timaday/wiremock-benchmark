package bench;

import com.github.tomakehurst.wiremock.extension.*;
import com.github.tomakehurst.wiremock.http.HttpHeaders;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: dispatch WireMock lifecycle callbacks to durable capture and HTTP metrics.
 * Must not: serve metric projections or perform broker IO on callback threads.
 * Contract: docs/CONTRACT.md and docs/PORTAINER.md.
 */
public final class CaptureExtension implements ServeEventListener {
  private DurableOutbox outbox;
  private RabbitPublisher publisher;
  private MetricsServer metrics;
  private final HttpMetrics http = new HttpMetrics();
  private final AtomicLong errors = new AtomicLong();
  private boolean enabled;

  public String getName() {
    return "durable-rabbit-capture";
  }

  public void start() {
    try {
      String setting = Settings.required("CAPTURE_ENABLED");
      if (!List.of("true", "false").contains(setting))
        throw new IllegalArgumentException("CAPTURE_ENABLED must be true or false");
      enabled = Boolean.parseBoolean(setting);
      if (enabled) {
        outbox = new DurableOutbox(Path.of(Settings.required("OUTBOX_PATH")), 1024);
        publisher = new RabbitPublisher(outbox);
      }
      metrics = new MetricsServer(enabled, outbox, publisher, errors, http);
    } catch (Exception e) {
      throw new IllegalStateException("Capture startup failed", e);
    }
  }

  public void beforeMatch(ServeEvent event, Parameters parameters) {
    if (isBenchmark(event)) http.received();
    capture(event, Phase.REQUEST);
  }

  public void beforeResponseSent(ServeEvent event, Parameters parameters) {
    capture(event, Phase.RESPONSE_PREPARED);
  }

  public void afterComplete(ServeEvent event, Parameters parameters) {
    capture(event, Phase.SEND_COMPLETED);
    if (isBenchmark(event))
      http.completed(event.getResponse().getStatus(), event.getTiming().getTotalTime());
  }

  private static boolean isBenchmark(ServeEvent event) {
    return event.getRequest().getUrl().startsWith("/bench/");
  }

  private void capture(ServeEvent event, Phase phase) {
    if (!enabled || !isBenchmark(event)) return;
    try {
      var request = event.getRequest();
      String requestId = request.getHeader("X-Bench-Id"), runId = request.getHeader("X-Bench-Run");
      if (requestId == null || runId == null)
        throw new IllegalArgumentException("Benchmark correlation headers required");
      String id = event.getId() + ":" + phase;
      byte[] body =
          phase == Phase.REQUEST
              ? request.getBody()
              : phase == Phase.RESPONSE_PREPARED ? event.getResponse().getBody() : new byte[0];
      HttpHeaders headers =
          phase == Phase.REQUEST
              ? request.getHeaders()
              : phase == Phase.RESPONSE_PREPARED
                  ? event.getResponse().getHeaders()
                  : new HttpHeaders();
      var values = new LinkedHashMap<String, List<String>>();
      for (var header : headers.all()) values.put(header.key(), header.values());
      var record =
          new CaptureEvent(
              id,
              runId,
              requestId,
              phase,
              System.currentTimeMillis(),
              request.getMethod().getName(),
              request.getUrl(),
              phase == Phase.REQUEST ? 0 : event.getResponse().getStatus(),
              values,
              Base64.getEncoder().encodeToString(body));
      outbox.append(id, CaptureCodec.encode(record));
    } catch (Throwable failure) {
      errors.incrementAndGet();
      System.err.println(
          "FATAL: durable capture unavailable; terminating rather than silently losing records");
      Runtime.getRuntime().halt(70);
    }
  }

  public void stop() {
    try {
      if (metrics != null) metrics.close();
      if (outbox != null) outbox.close();
      if (publisher != null) publisher.close();
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
}
