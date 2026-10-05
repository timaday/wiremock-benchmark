package bench;

import com.rabbitmq.client.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Responsibility: enforce the shared persistent, mandatory RabbitMQ batch-confirm protocol.
 * Must not: retry, buffer to disk or decide caller success before every confirmation.
 * Contract: docs/CONTRACT.md, durable capture and direct RabbitMQ capture.
 */
final class RabbitCaptureBatch implements ConfirmedCaptureBatch {
  private final Connection connection;
  private final Channel channel;
  private final String queue;
  private final AtomicBoolean returned = new AtomicBoolean();

  RabbitCaptureBatch(Connection connection, Channel channel, String queue) throws Exception {
    this.connection = connection;
    this.channel = channel;
    this.queue = queue;
    channel.confirmSelect();
    channel.addReturnListener(message -> returned.set(true));
  }

  public void publish(List<OutboxRow> batch, int timeoutMs) throws Exception {
    returned.set(false);
    for (var row : batch) {
      channel.basicPublish("", queue, true, new AMQP.BasicProperties.Builder()
          .deliveryMode(2).contentType(CaptureCodec.CONTENT_TYPE)
          .contentEncoding(CaptureCodec.CONTENT_ENCODING).messageId(row.id()).build(), row.payload());
    }
    channel.waitForConfirmsOrDie(timeoutMs);
    if (returned.get()) throw new IllegalStateException("Capture returned unroutable");
  }

  public boolean connected() { return connection.isOpen() && channel.isOpen(); }

  public void close() { connection.abort(1000); }
}
