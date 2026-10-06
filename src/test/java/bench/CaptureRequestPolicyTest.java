package bench;

import static org.junit.jupiter.api.Assertions.*;

import com.github.tomakehurst.wiremock.http.*;
import java.lang.reflect.Proxy;
import java.util.*;
import org.junit.jupiter.api.Test;

class CaptureRequestPolicyTest {
  @Test void stubModeAcceptsRequestsWithoutHeadersOnAnyStubPathButBoundsBodySize() {
    for (String path : List.of("/transaction", "/bench/custom")) {
      assertEquals(CaptureAdmission.ACCEPTED,
          CaptureRequestPolicy.evaluate(request(path, Map.of(), 1024), CaptureIdentityMode.STUB_JSON));
      assertEquals(CaptureAdmission.REQUEST_TOO_LARGE,
          CaptureRequestPolicy.evaluate(request(path, Map.of(), 65537), CaptureIdentityMode.STUB_JSON));
    }
  }
  private Request request(String path, Map<String, List<String>> headers, int bytes) {
    return (Request) Proxy.newProxyInstance(Request.class.getClassLoader(), new Class<?>[] {Request.class},
        (proxy, method, args) -> switch (method.getName()) {
          case "getUrl" -> path;
          case "getBody" -> new byte[bytes];
          case "header" -> headers.containsKey(args[0])
              ? new HttpHeader((String) args[0], headers.get(args[0])) : HttpHeader.absent((String) args[0]);
          default -> throw new AssertionError("Unexpected request access: " + method.getName());
        });
  }

  private Map<String, List<String>> validHeaders() {
    return Map.of(CaptureRequestPolicy.RUN_ID, List.of("run"), CaptureRequestPolicy.REQUEST_ID, List.of("request"));
  }

  @Test
  void acceptsLargestWorkloadAndExactAdmissionBoundary() {
    for (int bytes : new int[] {0, 50 * 1024, 64 * 1024})
      assertEquals(CaptureAdmission.ACCEPTED, CaptureRequestPolicy.evaluate(request("/bench/test", validHeaders(), bytes)));
  }

  @Test
  void rejectsMissingBlankDuplicatedAndOverlongCorrelation() {
    for (String key : List.of(CaptureRequestPolicy.RUN_ID, CaptureRequestPolicy.REQUEST_ID)) {
      for (var values : List.of(List.<String>of(), List.of(""), List.of(" "), List.of("a", "b"), List.of("x".repeat(257)))) {
        var headers = new HashMap<>(validHeaders());
        if (values.isEmpty()) headers.remove(key); else headers.put(key, values);
        assertEquals(CaptureAdmission.INVALID_CORRELATION,
            CaptureRequestPolicy.evaluate(request("/bench/test", headers, 1024)));
      }
    }
  }

  @Test
  void rejectsOversizedRequestsWithoutCallingAnyCaptureSink() {
    assertEquals(CaptureAdmission.REQUEST_TOO_LARGE,
        CaptureRequestPolicy.evaluate(request("/bench/test", validHeaders(), 64 * 1024 + 1)));
  }

  @Test
  void leavesNonBenchmarkRequestsAndHealthChecksAlone() {
    for (String path : List.of("/__admin/health", "/unmatched", "/"))
      assertEquals(CaptureAdmission.ACCEPTED, CaptureRequestPolicy.evaluate(request(path, Map.of(), 0)));
  }
}
