package bench;

import com.github.tomakehurst.wiremock.extension.*;
import com.github.tomakehurst.wiremock.extension.requestfilter.*;
import com.github.tomakehurst.wiremock.http.HttpHeaders;
import com.github.tomakehurst.wiremock.http.Request;
import com.github.tomakehurst.wiremock.client.ResponseDefinitionBuilder;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: dispatch WireMock lifecycle callbacks to durable capture and HTTP metrics.
 * Must not: serve metric projections or perform broker IO on callback threads.
 * Contract: docs/CONTRACT.md and docs/PORTAINER.md.
 */
public final class CaptureExtension implements ServeEventListener, StubRequestFilterV2 {
  private CaptureSink sink;
  private MetricsServer metrics;
  private final HttpMetrics http = new HttpMetrics();
  private final AtomicLong errors = new AtomicLong();
  private final AtomicLong rejected = new AtomicLong();
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
        sink = switch (CaptureMode.valueOf(Settings.required("CAPTURE_MODE"))) {
          case OUTBOX -> new OutboxCaptureSink(Path.of(Settings.required("OUTBOX_PATH")));
          case DIRECT_RABBIT -> DirectRabbitCaptureSink.configured();
        };
      }
      metrics = new MetricsServer(sink, errors, rejected, http);
    } catch (Exception e) {
      if (sink != null) {
        try { sink.close(); } catch (Exception closeFailure) { e.addSuppressed(closeFailure); }
      }
      throw new IllegalStateException("Capture startup failed", e);
    }
  }

  public RequestFilterAction filter(Request request, ServeEvent event) {
    var admission = enabled ? CaptureRequestPolicy.evaluate(request) : CaptureAdmission.ACCEPTED;
    if (admission == CaptureAdmission.ACCEPTED) return RequestFilterAction.continueWith(request);
    rejected.incrementAndGet();
    return RequestFilterAction.stopWith(ResponseDefinitionBuilder.responseDefinition()
        .withStatus(admission.status).withHeader("Content-Type", "text/plain; charset=utf-8")
        .withBody(admission.message).build());
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

  private boolean isBenchmark(ServeEvent event) {
    return CaptureRequestPolicy.isBenchmark(event.getRequest())
        && (!enabled || CaptureRequestPolicy.evaluate(event.getRequest()) == CaptureAdmission.ACCEPTED);
  }

  private void capture(ServeEvent event, Phase phase) {
    if (!enabled || !isBenchmark(event)) return;
    try {
      var request = event.getRequest();
      String requestId = request.getHeader(CaptureRequestPolicy.REQUEST_ID);
      String runId = request.getHeader(CaptureRequestPolicy.RUN_ID);
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
      sink.append(id, CaptureCodec.encode(record));
    } catch (Throwable failure) {
      errors.incrementAndGet();
      System.err.println(
          "FATAL: durable capture unavailable (" + failure.getClass().getSimpleName()
              + "); terminating rather than silently losing records");
      Runtime.getRuntime().halt(70);
    }
  }

  public void stop() {
    try {
      if (metrics != null) metrics.close();
      if (sink != null) sink.close();
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
}
