package bench;

import com.github.tomakehurst.wiremock.http.ResponseDefinition;
import com.jayway.jsonpath.JsonPath;
import java.util.Map;
import java.util.Set;

/**
 * Responsibility: parse and validate the single per-stub capture configuration contract.
 * Must not: infer configuration or extract request data. Contract: docs/CONTRACT.md.
 */
record StubCaptureRule(String runId, JsonPath path, MissingCorrelationPolicy missingCorrelation) {
  static final String PARAMETER = "capture";
  private static final String RUN = "runId", PATH = "correlationJsonPath", MISSING = "missingCorrelation";
  static final int MAX_ID_CHARACTERS = 256;

  static boolean selected(ResponseDefinition response) {
    return response != null && response.getTransformerParameters() != null
        && response.getTransformerParameters().containsKey(PARAMETER);
  }

  static StubCaptureRule parse(ResponseDefinition response) {
    Object raw = response.getTransformerParameters().get(PARAMETER);
    if (!(raw instanceof Map<?, ?> values) || !values.keySet().equals(Set.of(RUN, PATH, MISSING)))
      throw new IllegalArgumentException("capture requires runId, correlationJsonPath and missingCorrelation only");
    String run = text(values, RUN);
    if (run.length() > MAX_ID_CHARACTERS) throw new IllegalArgumentException("capture.runId exceeds 256 characters");
    String expression = text(values, PATH);
    if (expression.length() > 1024 || !expression.startsWith("$"))
      throw new IllegalArgumentException("capture.correlationJsonPath must be an absolute JSONPath up to 1024 characters");
    JsonPath path;
    try { path = JsonPath.compile(expression); }
    catch (RuntimeException e) { throw new IllegalArgumentException("Invalid capture.correlationJsonPath"); }
    if (!path.isDefinite()) throw new IllegalArgumentException("capture.correlationJsonPath must select a single value");
    MissingCorrelationPolicy policy;
    try { policy = MissingCorrelationPolicy.valueOf(text(values, MISSING)); }
    catch (IllegalArgumentException e) { throw new IllegalArgumentException("capture.missingCorrelation must be RECORD_UNCORRELATED"); }
    return new StubCaptureRule(run, path, policy);
  }

  private static String text(Map<?, ?> values, String key) {
    if (!(values.get(key) instanceof String value) || value.isBlank())
      throw new IllegalArgumentException("capture." + key + " must be a nonblank string");
    return value;
  }
}
