package bench;

/**
 * Responsibility: accept captures at the explicitly configured durability boundary.
 * Must not: return success for memory-only admission.
 * Contract: docs/CONTRACT.md, durable capture and direct RabbitMQ capture.
 */
interface CaptureSink extends AutoCloseable {
  void append(String id, byte[] payload) throws Exception;
  CaptureSnapshot snapshot();
  void exposeDiagnostics(StringBuilder output);
}
