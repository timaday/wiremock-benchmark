package bench;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: bound memory admission and wait for broker durability without a local spool.
 * Must not: return on admission, retry uncertain publishes or survive a failed durability boundary.
 * Contract: docs/CONTRACT.md, direct RabbitMQ capture.
 */
final class DirectRabbitCaptureSink implements CaptureSink {
  private static final int CAPACITY = 1024;
  private static final int MAX_BATCH = 256;
  private final ConfirmedCaptureBatch publisher;
  private final int timeoutMs;
  private final int capacity;
  private final ArrayBlockingQueue<DirectCaptureOperation> queue;
  private final Set<DirectCaptureOperation> outstanding = new HashSet<>();
  private final Object lock = new Object();
  private final Thread worker;
  private final AtomicLong confirmed = new AtomicLong();
  private final DurationMetric appendWait = new DurationMetric();
  private final DurationMetric publishConfirms = new DurationMetric();
  private volatile Exception failure;

  static DirectRabbitCaptureSink configured() throws Exception {
    int timeout = Settings.positiveNumber("CAPTURE_CONFIRM_TIMEOUT_MS");
    String queue = Settings.required("RABBIT_QUEUE");
    var type = RabbitQueueType.configured();
    var factory = RabbitPublisher.factory();
    factory.setChannelRpcTimeout(timeout);
    var connection = factory.newConnection("wiremock-direct-capture");
    try {
      var channel = connection.createChannel();
      channel.queueDeclare(queue, true, false, false, Map.of("x-queue-type", type.name()));
      return new DirectRabbitCaptureSink(new RabbitCaptureBatch(connection, channel, queue),
          CAPACITY, timeout);
    } catch (Exception e) {
      connection.abort(1000);
      throw e;
    }
  }

  DirectRabbitCaptureSink(ConfirmedCaptureBatch publisher, int capacity, int timeoutMs) {
    if (capacity <= 0 || timeoutMs <= 0) throw new IllegalArgumentException("Positive bounds required");
    this.publisher = publisher;
    this.capacity = capacity;
    this.timeoutMs = timeoutMs;
    queue = new ArrayBlockingQueue<>(capacity);
    worker = new Thread(this::loop, "capture-direct-rabbit");
    worker.setDaemon(true);
    worker.start();
  }

  public void append(String id, byte[] payload) throws Exception {
    long started = System.nanoTime();
    var operation = new DirectCaptureOperation(new OutboxRow(id, payload), new CompletableFuture<>());
    try {
      synchronized (lock) {
        if (failure != null) throw new IllegalStateException("Capture publisher unavailable", failure);
        if (outstanding.size() >= capacity) throw new IllegalStateException("Capture admission full");
        outstanding.add(operation);
        queue.add(operation);
      }
      operation.accepted().get(timeoutMs, TimeUnit.MILLISECONDS);
    } catch (Exception e) {
      fail(e);
      if (e instanceof InterruptedException) Thread.currentThread().interrupt();
      throw e;
    } finally {
      appendWait.record(System.nanoTime() - started);
    }
  }

  private void loop() {
    try {
      while (failure == null) {
        var first = queue.poll(100, TimeUnit.MILLISECONDS);
        if (first == null) continue;
        var batch = new ArrayList<DirectCaptureOperation>();
        batch.add(first);
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(2);
        while (batch.size() < MAX_BATCH) {
          long remaining = deadline - System.nanoTime();
          if (remaining <= 0) break;
          var next = queue.poll(remaining, TimeUnit.NANOSECONDS);
          if (next == null) break;
          batch.add(next);
        }
        if (failure != null) return;
        long started = System.nanoTime();
        publisher.publish(batch.stream().map(DirectCaptureOperation::row).toList(), timeoutMs);
        publishConfirms.record(System.nanoTime() - started);
        synchronized (lock) {
          if (failure != null) return;
          confirmed.addAndGet(batch.size());
          for (var operation : batch) {
            outstanding.remove(operation);
            operation.accepted().complete(null);
          }
        }
      }
    } catch (Exception e) {
      fail(e);
    }
  }

  private void fail(Exception reason) {
    synchronized (lock) {
      if (failure != null) return;
      failure = reason;
      for (var operation : outstanding) operation.accepted().completeExceptionally(reason);
      outstanding.clear();
      queue.clear();
    }
  }

  public CaptureSnapshot snapshot() {
    synchronized (lock) {
      return new CaptureSnapshot(CaptureMode.DIRECT_RABBIT, outstanding.size(), confirmed.get(),
          confirmed.get(), failure == null && publisher.connected(), 0,
          Map.of("queuedOperations", queue.size(), "append_wait", appendWait.snapshot(),
              "publish_confirm", publishConfirms.snapshot()));
    }
  }

  public void exposeDiagnostics(StringBuilder output) {
    HttpMetrics.metric(output, "wiremock_capture_queued_operations", "gauge", queue.size());
    appendWait.expose(output, "wiremock_capture_append_wait");
    publishConfirms.expose(output, "wiremock_capture_publish_confirm");
  }

  public void close() throws InterruptedException {
    fail(new IllegalStateException("Capture publisher closed"));
    worker.interrupt();
    publisher.close();
    worker.join(2000);
  }
}
