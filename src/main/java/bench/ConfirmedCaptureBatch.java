package bench;

import java.util.List;

/**
 * Responsibility: publish a batch and establish mandatory routing and broker confirmation.
 * Must not: treat socket writes, returns or negative acknowledgements as acceptance.
 * Contract: docs/CONTRACT.md, RabbitMQ durability boundaries.
 */
interface ConfirmedCaptureBatch extends AutoCloseable {
  void publish(List<OutboxRow> batch, int timeoutMs) throws Exception;
  boolean connected();
  void close();
}
