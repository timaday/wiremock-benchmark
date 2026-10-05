package bench;

import com.rabbitmq.client.*;
import java.util.concurrent.atomic.*;

/**
 * Responsibility: publish durable outbox events and request deletion after broker confirmation.
 * Must not: mutate SQLite directly or acknowledge events before mandatory routing and confirms.
 * Contract: docs/CONTRACT.md, durable capture and capture diagnostics.
 */
final class RabbitPublisher implements AutoCloseable {
  private final DurableOutbox outbox;
  private final Thread worker;
  private volatile boolean running = true;
  volatile boolean connected;
  final AtomicLong confirmed = new AtomicLong(), reconnects = new AtomicLong();
  final DurationMetric reads = new DurationMetric();
  final DurationMetric publishConfirms = new DurationMetric();
  final DurationMetric deletions = new DurationMetric();

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
        var batchPublisher = new RabbitCaptureBatch(connection, channel, Settings.required("RABBIT_QUEUE"));
        connected = true;
        while (running && connection.isOpen()) {
          long started = System.nanoTime();
          var batch = outbox.read(256);
          reads.record(System.nanoTime() - started);
          if (batch.isEmpty()) {
            Thread.sleep(10);
            continue;
          }
          started = System.nanoTime();
          batchPublisher.publish(batch, 10000);
          publishConfirms.record(System.nanoTime() - started);
          started = System.nanoTime();
          outbox.confirmed(batch);
          deletions.record(System.nanoTime() - started);
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
