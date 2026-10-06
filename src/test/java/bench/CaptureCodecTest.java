package bench;

import static org.junit.jupiter.api.Assertions.*;

import java.io.*;
import java.util.*;
import java.util.zip.*;
import org.junit.jupiter.api.Test;

class CaptureCodecTest {
  @Test
  void emptyResponseKeepsCorrelationAndMissingCorrelationIsExplicit() throws Exception {
    for (var status : CorrelationStatus.values()) {
      var event = new CaptureEvent(2, "event", "run", "internal-id",
          status == CorrelationStatus.PRESENT ? "business-id" : "", status,
          Phase.RESPONSE_PREPARED, 123, "POST", "/transaction", 200, Map.of(), "");
      assertEquals(event, CaptureCodec.decode(CaptureCodec.encode(event)));
    }
    assertThrows(IllegalArgumentException.class, () -> new CaptureEvent(1, "event", "run", "id",
        "id", CorrelationStatus.PRESENT, Phase.REQUEST, 0, "POST", "/", 0, Map.of(), ""));
  }

  @Test
  void retainsBinaryBodiesHeadersAndIdentity() throws Exception {
    byte[] body = new byte[51200];
    new Random(522).nextBytes(body);
    var event =
        new CaptureEvent(
            2, "event",
            "run",
            "request", "request", CorrelationStatus.PRESENT,
            Phase.RESPONSE_PREPARED,
            123,
            "POST",
            "/bench/example",
            200,
            Map.of("X-Multi", List.of("one", "two")),
            Base64.getEncoder().encodeToString(body));
    assertEquals(event, CaptureCodec.decode(CaptureCodec.encode(event)));
  }

  @Test
  void corruptAndOversizeCapturesFailExplicitly() throws Exception {
    assertThrows(IOException.class, () -> CaptureCodec.decode(new byte[] {1, 2, 3}));
    var output = new ByteArrayOutputStream();
    try (var zip = new DeflaterOutputStream(output)) {
      zip.write(new byte[CaptureCodec.MAX_EVENT_BYTES + 1]);
    }
    assertThrows(IOException.class, () -> CaptureCodec.decode(output.toByteArray()));
  }
}
