package bench;

import com.github.tomakehurst.wiremock.http.Request;

/**
 * Responsibility: validate benchmark capture admission before any durable event is created.
 * Must not: perform IO, validate fixture JSON schemas or convert storage errors into HTTP 400.
 * Contract: docs/CONTRACT.md, client validation.
 */
final class CaptureRequestPolicy {
  static final String REQUEST_ID = "X-Bench-Id";
  static final String RUN_ID = "X-Bench-Run";
  private static final int MAX_ID_CHARACTERS = 256;
  private static final int MAX_REQUEST_BYTES = 64 * 1024;

  static boolean isBenchmark(Request request) { return request.getUrl().startsWith("/bench/"); }

  static CaptureAdmission evaluate(Request request) {
    if (!isBenchmark(request)) return CaptureAdmission.ACCEPTED;
    if (!validHeader(request, REQUEST_ID) || !validHeader(request, RUN_ID))
      return CaptureAdmission.INVALID_CORRELATION;
    if (request.getBody().length > MAX_REQUEST_BYTES) return CaptureAdmission.REQUEST_TOO_LARGE;
    return CaptureAdmission.ACCEPTED;
  }

  private static boolean validHeader(Request request, String name) {
    var header = request.header(name);
    if (!header.isPresent() || header.values().size() != 1) return false;
    String value = header.firstValue();
    return value != null && !value.isBlank() && value.length() <= MAX_ID_CHARACTERS;
  }
}
