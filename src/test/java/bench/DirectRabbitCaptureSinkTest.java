package bench;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;

class DirectRabbitCaptureSinkTest {
  private static final class ControlledPublisher implements ConfirmedCaptureBatch {
    final CountDownLatch entered = new CountDownLatch(1);
    final CountDownLatch confirmed = new CountDownLatch(1);
    final List<OutboxRow> received = new CopyOnWriteArrayList<>();
    volatile boolean connected = true;
    volatile Exception failure;

    public void publish(List<OutboxRow> batch, int timeoutMs) throws Exception {
      received.addAll(batch);
      entered.countDown();
      if (!confirmed.await(5, TimeUnit.SECONDS)) throw new TimeoutException();
      if (failure != null) throw failure;
    }
    public boolean connected() { return connected; }
    public void close() { connected = false; confirmed.countDown(); }
  }

  @Test
  void callbacksWaitForConfirmationAndCountersOnlyAdvanceAfterIt() throws Exception {
    var transport = new ControlledPublisher();
    var pool = Executors.newSingleThreadExecutor();
    try (var sink = new DirectRabbitCaptureSink(transport, 4, 2000)) {
      var call = pool.submit(() -> { sink.append("event", new byte[] {1, 2}); return null; });
      assertTrue(transport.entered.await(1, TimeUnit.SECONDS));
      assertThrows(TimeoutException.class, () -> call.get(50, TimeUnit.MILLISECONDS));
      assertEquals(1, sink.snapshot().pending());
      assertEquals(0, sink.snapshot().confirmed());
      transport.confirmed.countDown();
      call.get(1, TimeUnit.SECONDS);
      assertEquals(1, sink.snapshot().committed());
      assertEquals(1, sink.snapshot().confirmed());
      assertEquals(0, sink.snapshot().pending());
      assertEquals("event", transport.received.get(0).id());
      assertArrayEquals(new byte[] {1, 2}, transport.received.get(0).payload());
    } finally { pool.shutdownNow(); }
  }

  @Test
  void admissionLimitIncludesBatchAlreadyWaitingForConfirmation() throws Exception {
    var transport = new ControlledPublisher();
    var pool = Executors.newSingleThreadExecutor();
    try (var sink = new DirectRabbitCaptureSink(transport, 1, 2000)) {
      var first = pool.submit(() -> { sink.append("first", new byte[] {1}); return null; });
      assertTrue(transport.entered.await(1, TimeUnit.SECONDS));
      assertThrows(IllegalStateException.class, () -> sink.append("overflow", new byte[] {2}));
      assertThrows(ExecutionException.class, () -> first.get(1, TimeUnit.SECONDS));
      transport.confirmed.countDown();
      assertThrows(IllegalStateException.class, () -> sink.append("later", new byte[] {3}));
      assertEquals(0, sink.snapshot().confirmed());
      assertFalse(sink.snapshot().brokerConnected());
    } finally { pool.shutdownNow(); }
  }

  @Test
  void deadlineFailsWithoutWaitingForeverForBlockedNetworkWriter() throws Exception {
    var transport = new ControlledPublisher();
    try (var sink = new DirectRabbitCaptureSink(transport, 4, 100)) {
      assertThrows(TimeoutException.class, () -> sink.append("timeout", new byte[] {1}));
      assertEquals(0, sink.snapshot().confirmed());
      assertThrows(IllegalStateException.class, () -> sink.append("late", new byte[] {2}));
      assertFalse(sink.snapshot().brokerConnected());
    }
  }

  @Test
  void negativeOrUncertainBrokerOutcomeFailsAllWaitersAndNeverRetries() throws Exception {
    var transport = new ControlledPublisher();
    transport.failure = new IOException("Simulated broker nack/connection loss");
    var pool = Executors.newFixedThreadPool(8);
    try (var sink = new DirectRabbitCaptureSink(transport, 16, 2000)) {
      var calls = new ArrayList<Future<?>>();
      for (int i = 0; i < 8; i++) {
        String id = "event-" + i;
        calls.add(pool.submit(() -> { sink.append(id, new byte[] {1}); return null; }));
      }
      assertTrue(transport.entered.await(1, TimeUnit.SECONDS));
      transport.confirmed.countDown();
      for (var call : calls) assertThrows(ExecutionException.class, () -> call.get(1, TimeUnit.SECONDS));
      assertEquals(0, sink.snapshot().confirmed());
      assertFalse(sink.snapshot().brokerConnected());
      assertThrows(IllegalStateException.class, () -> sink.append("late", new byte[] {2}));
      assertEquals(transport.received.size(), transport.received.stream().map(OutboxRow::id).distinct().count());
    } finally { pool.shutdownNow(); }
  }

  @Test
  void closeFailsPendingAndRejectsNewOperations() throws Exception {
    var transport = new ControlledPublisher();
    var sink = new DirectRabbitCaptureSink(transport, 4, 2000);
    var pool = Executors.newSingleThreadExecutor();
    try {
      var call = pool.submit(() -> { sink.append("event", new byte[] {1}); return null; });
      assertTrue(transport.entered.await(1, TimeUnit.SECONDS));
      sink.close();
      assertThrows(ExecutionException.class, () -> call.get(1, TimeUnit.SECONDS));
      assertThrows(IllegalStateException.class, () -> sink.append("late", new byte[] {2}));
      assertEquals(0, sink.snapshot().confirmed());
    } finally { sink.close(); pool.shutdownNow(); }
  }

  @Test
  void concurrentSuccessfulCallbacksPreserveEveryIdAndPayload() throws Exception {
    var transport = new ControlledPublisher();
    transport.confirmed.countDown();
    var pool = Executors.newFixedThreadPool(16);
    try (var sink = new DirectRabbitCaptureSink(transport, 64, 2000)) {
      var calls = new ArrayList<Future<?>>();
      for (int i = 0; i < 200; i++) {
        String id = "event-" + i;
        calls.add(pool.submit(() -> { sink.append(id, id.getBytes()); return null; }));
      }
      for (var call : calls) call.get(5, TimeUnit.SECONDS);
      assertEquals(200, transport.received.size());
      assertEquals(200, transport.received.stream().map(OutboxRow::id).distinct().count());
      for (var row : transport.received) assertArrayEquals(row.id().getBytes(), row.payload());
      assertEquals(200, sink.snapshot().confirmed());
      assertEquals(0, sink.snapshot().pending());
    } finally { pool.shutdownNow(); }
  }
}
