package bench;

import static org.junit.jupiter.api.Assertions.*;
import static com.github.tomakehurst.wiremock.client.ResponseDefinitionBuilder.responseDefinition;

import com.github.tomakehurst.wiremock.common.DataTruncationSettings;
import com.github.tomakehurst.wiremock.http.Response;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import com.github.tomakehurst.wiremock.verification.LoggedRequest;
import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

class CaptureLifecycleTest {
  @Test void identitySnapshotSurvivesMappingChangesBetweenCapturePhases() {
    var records = new ArrayList<CaptureEvent>();
    CaptureSink recording = new CaptureSink() {
      public void append(String id, byte[] payload) throws Exception { records.add(CaptureCodec.decode(payload)); }
      public CaptureSnapshot snapshot() { throw new UnsupportedOperationException("Not a durability test"); }
      public void exposeDiagnostics(StringBuilder output) { }
      public void close() { }
    };
    var lifecycle = new CaptureLifecycle(CaptureIdentityMode.STUB_JSON, recording, new HttpMetrics(), new AtomicLong());
    var request = com.github.tomakehurst.wiremock.common.Json.read(
        "{\"url\":\"/transaction\",\"absoluteUrl\":\"http://localhost/transaction\",\"method\":\"POST\","
        + "\"headers\":{},\"bodyAsBase64\":\""
        + java.util.Base64.getEncoder().encodeToString("{\"correlationId\":\"old\",\"requestId\":\"new\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8)) + "\"}",
        LoggedRequest.class);
    var event = ServeEvent.of(request).withResponseDefinition(responseDefinition().withStatus(200)
        .withTransformerParameter("capture", Map.of("runId", "old-run", "correlationJsonPath", "$.correlationId",
            "missingCorrelation", "RECORD_UNCORRELATED")).build());
    var identity = RequestCorrelation.extract(StubCaptureRule.parse(event.getResponseDefinition()),
        event.getId().toString(), request.getBody());
    var probe = ServeEvent.of(request);
    CaptureIdentitySnapshot.attach(probe, identity);
    assertEquals(identity, CaptureIdentitySnapshot.read(probe));
    assertNotNull(CaptureEventFactory.create(event, identity, Phase.REQUEST));
    lifecycle.afterMatch(event);
    // The same exchange now exposes changed configuration; subsequent phases
    // must use the snapshot rather than re-extracting from this definition.
    event = event.withResponseDefinition(responseDefinition().withStatus(200)
        .withTransformerParameter("capture", Map.of("runId", "new-run", "correlationJsonPath", "$.requestId",
            "missingCorrelation", "RECORD_UNCORRELATED")).build())
        .complete(Response.response().status(200).headers(new com.github.tomakehurst.wiremock.http.HttpHeaders())
            .body(new byte[0]).build(), DataTruncationSettings.NO_TRUNCATION);
    assertNotNull(CaptureEventFactory.create(event, identity, Phase.RESPONSE_PREPARED));
    lifecycle.beforeResponseSent(event);
    lifecycle.afterComplete(event);
    assertEquals(3, records.size());
    for (var record : records) {
      assertEquals("old-run", record.runId());
      assertEquals("old", record.correlationId());
      assertEquals(event.getId().toString(), record.requestId());
    }
    assertEquals("", records.get(1).bodyBase64());
    assertEquals(200, records.get(1).status());
  }
}
