package bench;

/**
 * Responsibility: name the explicitly selected capture durability boundary.
 * Must not: select a fallback when a sink fails.
 * Contract: docs/CONTRACT.md, direct RabbitMQ capture.
 */
enum CaptureMode { OUTBOX, DIRECT_RABBIT }
