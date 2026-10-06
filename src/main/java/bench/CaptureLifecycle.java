package bench;

import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: resolve capture identity once and coordinate durable lifecycle records.
 * Must not: own broker/storage protocols or change HTTP responses. Contract: docs/CONTRACT.md.
 */
final class CaptureLifecycle {
  private final CaptureIdentityMode mode;
  private final CaptureSink sink;
  private final HttpMetrics http;
  private final AtomicLong errors;

  CaptureLifecycle(CaptureIdentityMode mode, CaptureSink sink, HttpMetrics http, AtomicLong errors) {
    this.mode = mode; this.sink = sink; this.http = http; this.errors = errors;
  }

  void beforeMatch(ServeEvent event) {
    if (mode != CaptureIdentityMode.BENCHMARK_HEADERS || !CaptureRequestPolicy.isBenchmark(event.getRequest())) return;
    var request = event.getRequest();
    begin(event, new CaptureIdentity(request.getHeader(CaptureRequestPolicy.RUN_ID),
        request.getHeader(CaptureRequestPolicy.REQUEST_ID), request.getHeader(CaptureRequestPolicy.REQUEST_ID),
        CorrelationStatus.PRESENT));
  }

  void afterMatch(ServeEvent event) {
    if (mode != CaptureIdentityMode.STUB_JSON || !StubCaptureRule.selected(event.getResponseDefinition())) return;
    var rule = StubCaptureRule.parse(event.getResponseDefinition());
    begin(event, RequestCorrelation.extract(rule, event.getId().toString(), event.getRequest().getBody()));
  }

  private void begin(ServeEvent event, CaptureIdentity identity) {
    CaptureIdentitySnapshot.attach(event, identity);
    http.received();
    capture(event, Phase.REQUEST);
  }

  void beforeResponseSent(ServeEvent event) { capture(event, Phase.RESPONSE_PREPARED); }

  void afterComplete(ServeEvent event) {
    if (!CaptureIdentitySnapshot.exists(event)) return;
    capture(event, Phase.SEND_COMPLETED);
    http.completed(event.getResponse().getStatus(), event.getTiming().getTotalTime());
  }

  private void capture(ServeEvent event, Phase phase) {
    if (!CaptureIdentitySnapshot.exists(event)) return;
    try {
      var record = CaptureEventFactory.create(event, CaptureIdentitySnapshot.read(event), phase);
      sink.append(record.eventId(), CaptureCodec.encode(record));
    } catch (Throwable failure) {
      errors.incrementAndGet();
      System.err.println("FATAL: durable capture unavailable (" + failure.getClass().getSimpleName()
          + "); terminating rather than silently losing records");
      Runtime.getRuntime().halt(70);
    }
  }
}
