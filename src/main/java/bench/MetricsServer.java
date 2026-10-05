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

  MetricsServer(CaptureSink sink, AtomicLong errors, AtomicLong rejected, HttpMetrics http) throws IOException {
    boolean enabled = sink != null;
    var disabledDiagnostics = new CaptureDiagnostics(false, null, null);
    server = HttpServer.create(new InetSocketAddress("0.0.0.0", 8081), 0);
    server.createContext("/metrics", exchange -> {
      try {
        var state = enabled ? sink.snapshot() : null;
        var values = new LinkedHashMap<String, Object>();
        values.put("mode", enabled ? state.mode().name() : "DISABLED");
        values.put("enabled", enabled);
        values.put("errors", errors.get());
        values.put("rejectedRequests", rejected.get());
        values.put("java", System.getProperty("java.runtime.version"));
        values.put("pending", enabled ? state.pending() : 0);
        values.put("committed", enabled ? state.committed() : 0);
        values.put("confirmed", enabled ? state.confirmed() : 0);
        values.put("brokerConnected", enabled && state.brokerConnected());
        values.put("reconnects", enabled ? state.reconnects() : 0);
        values.put("heapUsed", Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory());
        values.put("captureDiagnostics", enabled ? state.diagnostics() : disabledDiagnostics.snapshot());
        respond(exchange, "application/json", Json.bytes(values));
      } catch (Exception e) { exchange.sendResponseHeaders(500, -1); }
      finally { exchange.close(); }
    });
    server.createContext("/prometheus", exchange -> {
      try {
        var state = enabled ? sink.snapshot() : null;
        var out = new StringBuilder(http.exposition()).append(JvmMetrics.exposition());
        HttpMetrics.metric(out, "wiremock_capture_enabled", "gauge", enabled ? 1 : 0);
        HttpMetrics.metric(out, "wiremock_capture_errors_total", "counter", errors.get());
        HttpMetrics.metric(out, "wiremock_capture_rejected_requests_total", "counter", rejected.get());
        HttpMetrics.metric(out, "wiremock_capture_pending", "gauge", enabled ? state.pending() : 0);
        HttpMetrics.metric(out, "wiremock_capture_committed_total", "counter", enabled ? state.committed() : 0);
        HttpMetrics.metric(out, "wiremock_capture_confirmed_total", "counter", enabled ? state.confirmed() : 0);
        HttpMetrics.metric(out, "wiremock_capture_broker_connected", "gauge", enabled && state.brokerConnected() ? 1 : 0);
        if (enabled) sink.exposeDiagnostics(out); else disabledDiagnostics.expose(out);
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
