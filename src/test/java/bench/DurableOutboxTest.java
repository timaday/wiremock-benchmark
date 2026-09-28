package bench;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Path;
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
}
