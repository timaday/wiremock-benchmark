package bench;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Path;
import java.sql.DriverManager;
import java.time.Duration;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DurableOutboxTest {
  @TempDir Path root;

  @Test
  void survivesReopenAndDeletesOnlyConfirmedRows() throws Exception {
    try (var box = new DurableOutbox(root.resolve("outbox.db"), 4)) {
      box.append("one", new byte[] {1, 2, 3});
      box.append("two", new byte[] {4});
    }
    try (var box = new DurableOutbox(root.resolve("outbox.db"), 4)) {
      var batch = box.read(1);
      assertEquals("one", batch.get(0).id());
      assertArrayEquals(new byte[] {1, 2, 3}, batch.get(0).payload());
      box.confirmed(batch);
      assertEquals("two", box.read(10).get(0).id());
      assertEquals(1, box.pending());
    }
  }

  @Test
  void concurrentCallbacksCompleteOnlyAfterCommit() throws Exception {
    try (var box = new DurableOutbox(root.resolve("outbox.db"), 8)) {
      var pool = Executors.newFixedThreadPool(16);
      var tasks = new java.util.ArrayList<Future<?>>();
      for (int i = 0; i < 100; i++) {
        String id = "id-" + i;
        tasks.add(pool.submit(() -> box.append(id, id.getBytes())));
      }
      for (var task : tasks) task.get(10, TimeUnit.SECONDS);
      pool.shutdown();
      assertEquals(100, box.pending());
      assertEquals(100, box.committed.get());
    }
  }

  @Test
  void appendWaitsForDatabaseCommitAndIsVisibleFromIndependentConnection() throws Exception {
    Path path = root.resolve("blocked.db");
    try (var box = new DurableOutbox(path, 4);
         var lock = DriverManager.getConnection("jdbc:sqlite:" + path);
         var sql = lock.createStatement()) {
      sql.execute("BEGIN IMMEDIATE");
      var pool = Executors.newSingleThreadExecutor();
      try {
        var append = pool.submit(() -> box.append("durable", new byte[] {9}));
        assertThrows(TimeoutException.class, () -> append.get(150, TimeUnit.MILLISECONDS));
        assertEquals(0, box.committed.get());
        sql.execute("COMMIT");
        append.get(5, TimeUnit.SECONDS);
        try (var independent = DriverManager.getConnection("jdbc:sqlite:" + path);
             var query = independent.createStatement();
             var rows = query.executeQuery("SELECT payload FROM outbox WHERE id='durable'")) {
          assertTrue(rows.next());
          assertArrayEquals(new byte[] {9}, rows.getBytes(1));
        }
      } finally { pool.shutdownNow(); }
    }
  }

  @Test
  void concurrentPublisherDeletesOnlyConfirmedEventsAndRetainsTailOnReopen() throws Exception {
    Path path = root.resolve("concurrent.db");
    try (var box = new DurableOutbox(path, 8)) {
      var pool = Executors.newFixedThreadPool(9);
      try {
        var publisher = pool.submit(() -> {
          long deleted = 0;
          while (deleted < 800) {
            var rows = box.read(32);
            if (rows.isEmpty()) { Thread.sleep(1); continue; }
            box.confirmed(rows);
            deleted += rows.size();
          }
          return deleted;
        });
        var futures = new java.util.ArrayList<Future<?>>();
        for (int lane = 0; lane < 8; lane++) {
          final int identity = lane;
          futures.add(pool.submit(() -> {
            for (int i = 0; i < 100; i++) box.append(identity + "-" + i, new byte[] {1});
          }));
        }
        for (var future : futures) future.get(10, TimeUnit.SECONDS);
        assertEquals(800L, publisher.get(10, TimeUnit.SECONDS));
        assertEquals(0, box.pending());
        box.append("unconfirmed", new byte[] {7});
      } finally { pool.shutdownNow(); }
    }
    try (var reopened = new DurableOutbox(path, 4)) {
      assertEquals(1, reopened.pending());
      var rows = reopened.read(10);
      assertEquals("unconfirmed", rows.get(0).id());
      assertArrayEquals(new byte[] {7}, rows.get(0).payload());
      reopened.confirmed(rows);
      reopened.confirmed(rows); // Reconciliation may repeat an already applied deletion.
      assertEquals(0, reopened.pending());
    }
  }

  @Test
  void duplicateAppendFailsWriterAndRejectsSubsequentWorkWithoutHanging() throws Exception {
    try (var box = new DurableOutbox(root.resolve("duplicate.db"), 1)) {
      box.append("duplicate", new byte[] {1});
      assertTimeoutPreemptively(Duration.ofSeconds(5), () -> {
        assertThrows(CompletionException.class, () -> box.append("duplicate", new byte[] {2}));
        assertThrows(IllegalStateException.class, () -> box.append("later", new byte[] {3}));
      });
      assertFalse(box.healthy());
      assertEquals(1, box.pending());
      assertArrayEquals(new byte[] {1}, box.read(1).get(0).payload());
    }
  }

  @Test
  void closedOutboxRejectsNewOperations() throws Exception {
    var box = new DurableOutbox(root.resolve("closed.db"), 1);
    box.close();
    assertThrows(IllegalStateException.class, () -> box.append("late", new byte[] {1}));
  }
}
