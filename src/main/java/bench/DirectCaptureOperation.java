package bench;

import java.util.concurrent.CompletableFuture;

/**
 * Responsibility: associate an admitted event with its durability completion.
 * Must not: mark its own broker outcome.
 * Contract: docs/CONTRACT.md, direct RabbitMQ capture.
 */
record DirectCaptureOperation(OutboxRow row, CompletableFuture<Void> accepted) {}
