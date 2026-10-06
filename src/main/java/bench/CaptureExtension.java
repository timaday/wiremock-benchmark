package bench;

import com.github.tomakehurst.wiremock.extension.*;
import com.github.tomakehurst.wiremock.extension.requestfilter.*;
import com.github.tomakehurst.wiremock.common.Errors;
import com.github.tomakehurst.wiremock.common.InvalidInputException;
import com.github.tomakehurst.wiremock.stubbing.StubMapping;
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
public final class CaptureExtension implements ServeEventListener, StubRequestFilterV2, StubLifecycleListener {
  private CaptureSink sink;
  private MetricsServer metrics;
  private final HttpMetrics http = new HttpMetrics();
  private final AtomicLong errors = new AtomicLong();
  private final AtomicLong rejected = new AtomicLong();
  private boolean enabled;
  private CaptureIdentityMode identityMode;
  private CaptureLifecycle lifecycle;

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
        identityMode = CaptureIdentityMode.valueOf(Settings.required("CAPTURE_IDENTITY_MODE"));
        sink = switch (CaptureMode.valueOf(Settings.required("CAPTURE_MODE"))) {
          case OUTBOX -> new OutboxCaptureSink(Path.of(Settings.required("OUTBOX_PATH")));
          case DIRECT_RABBIT -> DirectRabbitCaptureSink.configured();
        };
      }
      if (enabled) lifecycle = new CaptureLifecycle(identityMode, sink, http, errors);
      metrics = new MetricsServer(sink, errors, rejected, http);
    } catch (Exception e) {
      if (sink != null) {
        try { sink.close(); } catch (Exception closeFailure) { e.addSuppressed(closeFailure); }
      }
      throw new IllegalStateException("Capture startup failed", e);
    }
  }

  public RequestFilterAction filter(Request request, ServeEvent event) {
    var admission = enabled ? CaptureRequestPolicy.evaluate(request, identityMode) : CaptureAdmission.ACCEPTED;
    if (admission == CaptureAdmission.ACCEPTED) return RequestFilterAction.continueWith(request);
    rejected.incrementAndGet();
    return RequestFilterAction.stopWith(ResponseDefinitionBuilder.responseDefinition()
        .withStatus(admission.status).withHeader("Content-Type", "text/plain; charset=utf-8")
        .withBody(admission.message).build());
  }

  public void beforeMatch(ServeEvent event, Parameters parameters) {
    if (enabled) lifecycle.beforeMatch(event);
    else if (CaptureRequestPolicy.isBenchmark(event.getRequest())) http.received();
  }

  public void afterMatch(ServeEvent event, Parameters parameters) {
    if (enabled) lifecycle.afterMatch(event);
  }

  public void beforeResponseSent(ServeEvent event, Parameters parameters) {
    if (enabled) lifecycle.beforeResponseSent(event);
  }

  public void afterComplete(ServeEvent event, Parameters parameters) {
    if (enabled) lifecycle.afterComplete(event);
    else if (CaptureRequestPolicy.isBenchmark(event.getRequest()))
      http.completed(event.getResponse().getStatus(), event.getTiming().getTotalTime());
  }

  public void beforeStubCreated(StubMapping mapping) { validate(mapping); }

  public void beforeStubEdited(StubMapping before, StubMapping after) { validate(after); }

  private void validate(StubMapping mapping) {
    if (!StubCaptureRule.selected(mapping.getResponse())) return;
    try { StubCaptureRule.parse(mapping.getResponse()); }
    catch (IllegalArgumentException e) {
      throw new InvalidInputException(Errors.singleWithDetail(400, "Invalid capture configuration", e.getMessage()));
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
