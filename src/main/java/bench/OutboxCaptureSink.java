package bench;

import java.nio.file.Path;

/**
 * Responsibility: own the existing SQLite outbox and its asynchronous publisher lifecycle.
 * Must not: change the commit-before-success or confirm-before-deletion boundaries.
 * Contract: docs/CONTRACT.md, durable capture.
 */
final class OutboxCaptureSink implements CaptureSink {
  private final DurableOutbox outbox;
  private final RabbitPublisher publisher;
  private final CaptureDiagnostics diagnostics;

  OutboxCaptureSink(Path path) throws Exception {
    outbox = new DurableOutbox(path, 1024);
    publisher = new RabbitPublisher(outbox);
    diagnostics = new CaptureDiagnostics(true, outbox, publisher);
  }

  public void append(String id, byte[] payload) { outbox.append(id, payload); }

  public CaptureSnapshot snapshot() {
    return new CaptureSnapshot(CaptureMode.OUTBOX, outbox.pending(), outbox.committed.get(),
        publisher.confirmed.get(), publisher.connected, publisher.reconnects.get(), diagnostics.snapshot());
  }

  public void exposeDiagnostics(StringBuilder output) { diagnostics.expose(output); }

  public void close() throws Exception {
    try { publisher.close(); } finally { outbox.close(); }
  }
}
