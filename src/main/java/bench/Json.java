package bench;

import com.fasterxml.jackson.databind.ObjectMapper;

/** Owns JSON encoding for benchmark artifacts, independent of WireMock's mapper. */
final class Json {
  static final ObjectMapper MAPPER = new ObjectMapper();

  static byte[] bytes(Object value) {
    try {
      return MAPPER.writeValueAsBytes(value);
    } catch (Exception e) {
      throw new IllegalArgumentException("Capture encoding failed", e);
    }
  }
}
