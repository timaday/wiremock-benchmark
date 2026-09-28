package bench;

import java.io.*;
import java.util.zip.*;

/** The single capture wire/storage encoding. HTTP response compression is unrelated. */
final class CaptureCodec {
  static final String CONTENT_TYPE = "application/json";
  static final String CONTENT_ENCODING = "deflate";
  static final int MAX_EVENT_BYTES = 1024 * 1024;

  static byte[] encode(CaptureEvent event) throws IOException {
    byte[] raw = Json.bytes(event);
    if (raw.length > MAX_EVENT_BYTES)
      throw new IOException("Capture envelope exceeds declared bound");
    var output = new ByteArrayOutputStream();
    var deflater = new Deflater(Deflater.BEST_SPEED);
    try (var stream = new DeflaterOutputStream(output, deflater)) {
      stream.write(raw);
    } finally {
      deflater.end();
    }
    return output.toByteArray();
  }

  static CaptureEvent decode(byte[] encoded) throws IOException {
    try (var stream = new InflaterInputStream(new ByteArrayInputStream(encoded))) {
      byte[] raw = stream.readNBytes(MAX_EVENT_BYTES + 1);
      if (raw.length > MAX_EVENT_BYTES)
        throw new IOException("Capture envelope exceeds declared bound");
      return Json.MAPPER.readValue(raw, CaptureEvent.class);
    }
  }
}
