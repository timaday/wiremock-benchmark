package bench;

/**
 * Responsibility: validate the explicitly selected RabbitMQ queue type at the boundary.
 * Must not: silently substitute a queue type.
 * Contract: docs/CONTRACT.md, direct RabbitMQ capture.
 */
enum RabbitQueueType {
  classic, quorum;

  static RabbitQueueType configured() {
    return valueOf(Settings.required("RABBIT_QUEUE_TYPE"));
  }
}
