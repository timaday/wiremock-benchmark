package bench;

import com.github.tomakehurst.wiremock.extension.*;
import com.github.tomakehurst.wiremock.http.HttpHeaders;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * WireMock lifecycle adapter. Durable intent precedes response emission; broker IO is delegated.
 */
public final class CaptureExtension implements ServeEventListener {
  private DurableOutbox outbox;
  private RabbitPublisher publisher;
  private HttpServer metrics;
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
      metrics = HttpServer.create(new InetSocketAddress("0.0.0.0", 8081), 0);
      metrics.createContext(
          "/metrics",
          exchange -> {
            try {
              var values = new LinkedHashMap<String, Object>();
              values.put("enabled", enabled);
              values.put("errors", errors.get());
              values.put("java", System.getProperty("java.runtime.version"));
              values.put("pending", enabled ? outbox.pending() : 0);
              values.put("committed", enabled ? outbox.committed.get() : 0);
              values.put("confirmed", enabled ? publisher.confirmed.get() : 0);
              values.put("brokerConnected", enabled && publisher.connected);
              values.put("reconnects", enabled ? publisher.reconnects.get() : 0);
              values.put(
                  "heapUsed",
                  Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory());
              byte[] body = Json.bytes(values);
              exchange.getResponseHeaders().add("Content-Type", "application/json");
              exchange.sendResponseHeaders(200, body.length);
              exchange.getResponseBody().write(body);
            } catch (Exception e) {
              exchange.sendResponseHeaders(500, -1);
            } finally {
              exchange.close();
            }
          });
      metrics.start();
    } catch (Exception e) {
      throw new IllegalStateException("Capture startup failed", e);
    }
  }

  public void beforeMatch(ServeEvent event, Parameters parameters) {
    capture(event, Phase.REQUEST);
  }

  public void beforeResponseSent(ServeEvent event, Parameters parameters) {
    capture(event, Phase.RESPONSE_PREPARED);
  }

  public void afterComplete(ServeEvent event, Parameters parameters) {
    capture(event, Phase.SEND_COMPLETED);
  }

  private void capture(ServeEvent event, Phase phase) {
    if (!enabled || !event.getRequest().getUrl().startsWith("/bench/")) return;
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
      if (metrics != null) metrics.stop(0);
      if (outbox != null) outbox.close();
      if (publisher != null) publisher.close();
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
}
