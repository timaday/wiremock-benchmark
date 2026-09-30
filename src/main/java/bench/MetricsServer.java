package bench;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: serve read-only JSON and Prometheus projections of runtime metrics.
 * Must not: write capture state, publish messages, or infer reconciliation success.
 * Contract: docs/PORTAINER.md and the existing JSON metrics contract.
 */
final class MetricsServer implements AutoCloseable {
  private final HttpServer server;

  MetricsServer(boolean enabled, DurableOutbox outbox, RabbitPublisher publisher,
      AtomicLong errors, HttpMetrics http) throws IOException {
    var diagnostics = new CaptureDiagnostics(enabled, outbox, publisher);
    server = HttpServer.create(new InetSocketAddress("0.0.0.0", 8081), 0);
    server.createContext("/metrics", exchange -> {
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
        values.put("heapUsed", Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory());
        values.put("captureDiagnostics", diagnostics.snapshot());
        respond(exchange, "application/json", Json.bytes(values));
      } catch (Exception e) { exchange.sendResponseHeaders(500, -1); }
      finally { exchange.close(); }
    });
    server.createContext("/prometheus", exchange -> {
      try {
        var out = new StringBuilder(http.exposition()).append(JvmMetrics.exposition());
        HttpMetrics.metric(out, "wiremock_capture_enabled", "gauge", enabled ? 1 : 0);
        HttpMetrics.metric(out, "wiremock_capture_errors_total", "counter", errors.get());
        HttpMetrics.metric(out, "wiremock_capture_pending", "gauge", enabled ? outbox.pending() : 0);
        HttpMetrics.metric(out, "wiremock_capture_committed_total", "counter", enabled ? outbox.committed.get() : 0);
        HttpMetrics.metric(out, "wiremock_capture_confirmed_total", "counter", enabled ? publisher.confirmed.get() : 0);
        HttpMetrics.metric(out, "wiremock_capture_broker_connected", "gauge", enabled && publisher.connected ? 1 : 0);
        diagnostics.expose(out);
        respond(exchange, "text/plain; version=0.0.4; charset=utf-8", out.toString().getBytes(StandardCharsets.UTF_8));
      } catch (Exception e) { exchange.sendResponseHeaders(500, -1); }
      finally { exchange.close(); }
    });
    server.start();
  }

  private static void respond(HttpExchange exchange, String type, byte[] body) throws IOException {
    exchange.getResponseHeaders().add("Content-Type", type);
    exchange.sendResponseHeaders(200, body.length);
    exchange.getResponseBody().write(body);
  }

  public void close() { server.stop(0); }
}
