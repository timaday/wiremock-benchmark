package bench;

import static org.junit.jupiter.api.Assertions.*;

import java.io.*;
import java.util.*;
import java.util.zip.*;
import org.junit.jupiter.api.Test;

class CaptureCodecTest {
  @Test
  void retainsBinaryBodiesHeadersAndIdentity() throws Exception {
    byte[] body = new byte[51200];
    new Random(522).nextBytes(body);
    var event =
        new CaptureEvent(
            "event",
            "run",
            "request",
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
