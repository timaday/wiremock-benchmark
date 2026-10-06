package bench;

import com.github.tomakehurst.wiremock.http.HttpHeaders;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Responsibility: project a serve event and frozen identity into the capture envelope.
 * Must not: resolve correlation, publish records or change responses. Contract: docs/CONTRACT.md.
 */
final class CaptureEventFactory {
  static CaptureEvent create(ServeEvent event, CaptureIdentity identity, Phase phase) {
    var request = event.getRequest();
    byte[] body = switch (phase) {
      case REQUEST -> request.getBody();
      case RESPONSE_PREPARED -> event.getResponse().getBody();
      case SEND_COMPLETED -> new byte[0];
    };
    HttpHeaders headers = switch (phase) {
      case REQUEST -> request.getHeaders();
      case RESPONSE_PREPARED -> event.getResponse().getHeaders();
      case SEND_COMPLETED -> new HttpHeaders();
    };
    var values = new LinkedHashMap<String, List<String>>();
    // WireMock represents absent response headers/body as null for an empty response.
    if (headers != null)
      for (var header : headers.all()) values.put(header.key(), header.values());
    return new CaptureEvent(CaptureEvent.SCHEMA_VERSION, event.getId() + ":" + phase,
        identity.runId(), identity.requestId(), identity.correlationId(), identity.correlationStatus(),
        phase, System.currentTimeMillis(), request.getMethod().getName(), request.getUrl(),
        phase == Phase.REQUEST ? 0 : event.getResponse().getStatus(), values,
        Base64.getEncoder().encodeToString(body == null ? new byte[0] : body));
  }
}
