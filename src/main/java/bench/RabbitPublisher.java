package bench;

import com.rabbitmq.client.*;
import java.util.concurrent.atomic.*;

/** Owns persistent mandatory publishing and confirms. Deletes only confirmed outbox batches. */
final class RabbitPublisher implements AutoCloseable {
  private final DurableOutbox outbox;
  private final Thread worker;
  private volatile boolean running = true;
  volatile boolean connected;
  final AtomicLong confirmed = new AtomicLong(), reconnects = new AtomicLong();

  RabbitPublisher(DurableOutbox outbox) {
    this.outbox = outbox;
    worker = new Thread(this::loop, "capture-rabbit-publisher");
    worker.start();
  }

  static ConnectionFactory factory() throws Exception {
    var factory = new ConnectionFactory();
    factory.setUri(Settings.required("RABBIT_URI"));
    factory.setAutomaticRecoveryEnabled(false);
    factory.setConnectionTimeout(3000);
    factory.setRequestedHeartbeat(10);
    return factory;
  }

  static void declare(Channel channel) throws Exception {
    channel.queueDeclare(Settings.required("RABBIT_QUEUE"), true, false, false, null);
  }

  private void loop() {
    while (running) {
      try (var connection = factory().newConnection("wiremock-capture");
          var channel = connection.createChannel()) {
        declare(channel);
        channel.confirmSelect();
        var returned = new AtomicBoolean();
        channel.addReturnListener(message -> returned.set(true));
        connected = true;
        while (running && connection.isOpen()) {
          var batch = outbox.read(256);
          if (batch.isEmpty()) {
            Thread.sleep(10);
            continue;
          }
          returned.set(false);
          for (var row : batch)
            channel.basicPublish(
                "",
                Settings.required("RABBIT_QUEUE"),
                true,
                new AMQP.BasicProperties.Builder()
                    .deliveryMode(2)
                    .contentType(CaptureCodec.CONTENT_TYPE)
                    .contentEncoding(CaptureCodec.CONTENT_ENCODING)
                    .messageId(row.id())
                    .build(),
                row.payload());
          channel.waitForConfirmsOrDie(10000);
          if (returned.get()) throw new IllegalStateException("Capture returned unroutable");
          outbox.confirmed(batch);
          confirmed.addAndGet(batch.size());
        }
      } catch (Exception e) {
        connected = false;
        reconnects.incrementAndGet();
        try {
          Thread.sleep(1000);
        } catch (InterruptedException interrupted) {
          Thread.currentThread().interrupt();
          return;
        }
      } finally {
        connected = false;
      }
    }
  }

  public void close() throws Exception {
    running = false;
    worker.interrupt();
    worker.join(15000);
  }
}
