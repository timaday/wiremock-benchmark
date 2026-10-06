package bench;

import com.github.tomakehurst.wiremock.stubbing.ServeEvent;

/**
 * Responsibility: attach/read the immutable identity on WireMock's per-request serve event.
 * Must not: retain a global request map or resolve identities again. Contract: docs/CONTRACT.md.
 */
final class CaptureIdentitySnapshot {
  private static final String TYPE = "bench.capture.identity";

  static boolean exists(ServeEvent event) {
    return event.getSubEvents().stream().anyMatch(item -> TYPE.equals(item.getType()));
  }

  static void attach(ServeEvent event, CaptureIdentity identity) {
    if (exists(event)) throw new IllegalStateException("Capture identity already resolved");
    event.appendSubEvent(TYPE, identity);
  }

  static CaptureIdentity read(ServeEvent event) {
    return event.getSubEvents().stream().filter(item -> TYPE.equals(item.getType()))
        .findFirst().orElseThrow(() -> new IllegalStateException("No capture identity"))
        .getDataAs(CaptureIdentity.class);
  }
}
