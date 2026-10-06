package bench;

import static org.junit.jupiter.api.Assertions.*;
import static com.github.tomakehurst.wiremock.client.ResponseDefinitionBuilder.responseDefinition;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RequestCorrelationTest {
  private StubCaptureRule rule(String path) {
    return StubCaptureRule.parse(responseDefinition().withTransformerParameter("capture", Map.of(
        "runId", "run-1", "correlationJsonPath", path,
        "missingCorrelation", "RECORD_UNCORRELATED")).build());
  }

  private CaptureIdentity extract(String path, String body) {
    return RequestCorrelation.extract(rule(path), "internal-id", body.getBytes(StandardCharsets.UTF_8));
  }

  @Test void readsTheSelectedFieldIncludingNestedAndEscapedValues() {
    var first = extract("$.correlationId", "{\"correlationId\":\"one\",\"requestId\":\"two\"}");
    var second = extract("$.requestId", "{\"correlationId\":\"one\",\"requestId\":\"two\"}");
    assertEquals("one", first.correlationId());
    assertEquals("two", second.correlationId());
    assertEquals("quote\"雪", extract("$.items[0].id", "{\"items\":[{\"id\":\"quote\\\"雪\"}]}").correlationId());
    assertEquals("internal-id", first.requestId());
    assertEquals(CorrelationStatus.PRESENT, first.correlationStatus());
  }

  @Test void missingValuesAreExplicitAndNeverUseAnotherField() {
    for (String body : new String[] {"{}", "null", "{\"requestId\":\"not-the-selected-field\"}",
        "{\"correlationId\":null}", "{\"correlationId\":\" \"}"}) {
      var identity = extract("$.correlationId", body);
      assertEquals(CorrelationStatus.MISSING, identity.correlationStatus(), body);
      assertEquals("", identity.correlationId());
      assertEquals("internal-id", identity.requestId());
    }
  }

  @Test void malformedBodiesAndWrongValueTypesDoNotThrow() {
    for (String body : new String[] {"", "{broken", "plain text", "{} trailing"})
      assertEquals(CorrelationStatus.INVALID_BODY, extract("$.correlationId", body).correlationStatus());
    for (String value : new String[] {"42", "true", "[]", "{}", "\"" + "x".repeat(257) + "\""})
      assertEquals(CorrelationStatus.INVALID_VALUE,
          extract("$.correlationId", "{\"correlationId\":" + value + "}").correlationStatus());
  }

  @Test void rejectsInvalidOrAmbiguousConfiguration() {
    for (String path : new String[] {"not-absolute", "$[", "$.items[*].id"})
      assertThrows(IllegalArgumentException.class, () -> rule(path));
    for (Map<String, Object> config : java.util.List.of(
        Map.<String, Object>of("runId", "run"),
        Map.<String, Object>of("runId", "run", "correlationJsonPath", "$.id", "missingCorrelation", "GUESS"),
        Map.<String, Object>of("runId", " ", "correlationJsonPath", "$.id", "missingCorrelation", "RECORD_UNCORRELATED")))
      assertThrows(IllegalArgumentException.class, () -> StubCaptureRule.parse(
          responseDefinition().withTransformerParameter("capture", config).build()));
  }
}
