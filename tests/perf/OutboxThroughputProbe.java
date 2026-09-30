package bench;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: measure real FULL/WAL outbox append/delete contention with a bounded workload.
 * Must not: substitute for HTTP qualification or simulate RabbitMQ durability.
 * Contract: docs/CONTRACT.md; args are a fresh database path, producer count and events per producer.
 */
public final class OutboxThroughputProbe {
  public static void main(String[] args) throws Exception {
    int producers = Integer.parseInt(args[1]), perProducer = Integer.parseInt(args[2]);
    long expected = (long) producers * perProducer;
    byte[] payload = new byte[512];
    new java.util.Random(1).nextBytes(payload);
    var pool = Executors.newFixedThreadPool(producers + 1);
    var released = new CountDownLatch(1);
    var deleted = new AtomicLong();
    var maximumPending = new AtomicLong();
    long start = System.nanoTime();
    try (var box = new DurableOutbox(Path.of(args[0]), 1024)) {
      var publisher = pool.submit(() -> {
        released.await();
        while (deleted.get() < expected) {
          var batch = box.read(256);
          if (batch.isEmpty()) { Thread.sleep(1); continue; }
          // Fixed synthetic confirmation delay; only the outbox is measured here.
          Thread.sleep(1);
          box.confirmed(batch);
          deleted.addAndGet(batch.size());
          maximumPending.accumulateAndGet(box.pending(), Math::max);
        }
        return null;
      });
      var futures = new ArrayList<Future<?>>();
      for (int lane = 0; lane < producers; lane++) {
        final int identity = lane;
        futures.add(pool.submit(() -> {
          released.await();
          for (int i = 0; i < perProducer; i++) box.append(identity + "-" + i, payload);
          return null;
        }));
      }
      released.countDown();
      for (var future : futures) future.get(120, TimeUnit.SECONDS);
      long appendEnd = System.nanoTime();
      publisher.get(120, TimeUnit.SECONDS);
      long end = System.nanoTime();
      if (box.pending() != 0 || box.committed.get() != expected || deleted.get() != expected)
        throw new AssertionError("Incomplete outbox lifecycle");
      System.out.printf(java.util.Locale.ROOT,
          "{\"events\":%d,\"appendSeconds\":%.3f,\"drainedSeconds\":%.3f,\"eventsPerSecond\":%.1f,\"maximumSampledPending\":%d}%n",
          expected, (appendEnd-start)/1e9, (end-start)/1e9, expected/((end-start)/1e9), maximumPending.get());
    } finally {
      pool.shutdownNow();
      if (!pool.awaitTermination(10, TimeUnit.SECONDS)) throw new AssertionError("Probe threads did not stop");
    }
  }
}
