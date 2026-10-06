package bench;

import com.jayway.jsonpath.Configuration;
import com.jayway.jsonpath.PathNotFoundException;
import com.jayway.jsonpath.spi.json.JacksonJsonProvider;
import com.jayway.jsonpath.spi.mapper.JacksonMappingProvider;
import com.fasterxml.jackson.databind.DeserializationFeature;
import java.io.IOException;

/**
 * Responsibility: extract one configured request-body value and classify its outcome.
 * Must not: change HTTP responses or manufacture business correlation. Contract: docs/CONTRACT.md.
 */
final class RequestCorrelation {
  private static final Configuration JSON_PATH = Configuration.builder()
      .jsonProvider(new JacksonJsonProvider(Json.MAPPER))
      .mappingProvider(new JacksonMappingProvider(Json.MAPPER)).build();

  static CaptureIdentity extract(StubCaptureRule rule, String requestId, byte[] body) {
    if (body == null || body.length == 0) return absent(rule, requestId, CorrelationStatus.INVALID_BODY);
    Object document;
    try { document = Json.MAPPER.readerFor(Object.class)
        .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readValue(body); }
    catch (IOException e) { return absent(rule, requestId, CorrelationStatus.INVALID_BODY); }
    if (document == null) return absent(rule, requestId, CorrelationStatus.MISSING);
    Object value;
    try { value = rule.path().read(document, JSON_PATH); }
    catch (PathNotFoundException e) { return absent(rule, requestId, CorrelationStatus.MISSING); }
    if (value == null || value instanceof String text && text.isBlank())
      return absent(rule, requestId, CorrelationStatus.MISSING);
    if (!(value instanceof String text) || text.length() > StubCaptureRule.MAX_ID_CHARACTERS)
      return absent(rule, requestId, CorrelationStatus.INVALID_VALUE);
    return new CaptureIdentity(rule.runId(), requestId, text, CorrelationStatus.PRESENT);
  }

  private static CaptureIdentity absent(StubCaptureRule rule, String requestId, CorrelationStatus status) {
    return switch (rule.missingCorrelation()) {
      case RECORD_UNCORRELATED -> new CaptureIdentity(rule.runId(), requestId, "", status);
    };
  }
}
