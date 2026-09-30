package bench;

import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Responsibility: serialize durable appends and confirmed deletions through one SQLite writer.
 * Must not: publish messages, acknowledge uncommitted captures, or own HTTP policy.
 * Contract: docs/CONTRACT.md, durable capture.
 */
final class DurableOutbox implements AutoCloseable {
  private final Path path;
  private final BlockingQueue<Pending> queue;
  private final Object lifecycle = new Object();
  private final Connection reader;
  private final Thread writer;
  private volatile boolean running = true;
  private volatile Throwable failure;
  private final AtomicLong pendingRows = new AtomicLong();
  final AtomicLong committed = new AtomicLong();
  final AtomicLong committedBytes = new AtomicLong();
  final AtomicLong maximumAppendBatch = new AtomicLong();
  final DurationMetric appendWait = new DurationMetric();
  final DurationMetric transactions = new DurationMetric();

  private record Pending(List<OutboxRow> appends, List<OutboxRow> deletes,
                         CompletableFuture<Void> durable) {}

  DurableOutbox(Path path, int capacity) throws Exception {
    this.path = path;
    queue = new ArrayBlockingQueue<>(capacity);
    Files.createDirectories(path.toAbsolutePath().getParent());
    Class.forName("org.sqlite.JDBC");
    reader = connect();
    try (var sql = reader.createStatement()) {
      sql.execute("CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
          + " id TEXT UNIQUE NOT NULL, payload BLOB NOT NULL)");
      try (var result = sql.executeQuery("SELECT count(*) FROM outbox")) {
        result.next();
        pendingRows.set(result.getLong(1));
      }
    } catch (SQLException error) {
      reader.close();
      throw error;
    }
    writer = new Thread(this::writeLoop, "capture-durable-writer");
    writer.start();
  }

  private Connection connect() throws SQLException {
    var connection = DriverManager.getConnection("jdbc:sqlite:" + path);
    try (var sql = connection.createStatement()) {
      sql.execute("PRAGMA journal_mode=WAL");
      sql.execute("PRAGMA synchronous=FULL");
      sql.execute("PRAGMA busy_timeout=30000");
      sql.execute("PRAGMA wal_autocheckpoint=1000");
    } catch (SQLException error) {
      connection.close();
      throw error;
    }
    return connection;
  }

  void append(String id, byte[] bytes) {
    long start = System.nanoTime();
    try {
      submit(new Pending(List.of(new OutboxRow(id, bytes)), List.of(), new CompletableFuture<>()));
    } finally { appendWait.record(System.nanoTime() - start); }
  }

  private void submit(Pending operation) {
    try {
      synchronized (lifecycle) {
        while (queue.remainingCapacity() == 0 && running && failure == null) lifecycle.wait();
        if (!running || failure != null) throw new IllegalStateException("Outbox unavailable", failure);
        queue.add(operation);
      }
      operation.durable().join();
    } catch (InterruptedException error) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Capture interrupted", error);
    }
  }

  private void writeLoop() {
    var batch = new ArrayList<Pending>(256);
    try (var connection = connect();
         var insert = connection.prepareStatement("INSERT INTO outbox(id,payload) VALUES(?,?)");
         var delete = connection.prepareStatement("DELETE FROM outbox WHERE id=?")) {
      connection.setAutoCommit(false);
      while (running || !queue.isEmpty()) {
        var first = queue.poll(100, TimeUnit.MILLISECONDS);
        if (first == null) continue;
        batch.add(first);
        long deadline = System.nanoTime() + 2_000_000L;
        while (batch.size() < 256) {
          long remaining = deadline - System.nanoTime();
          if (remaining <= 0) break;
          var item = queue.poll(remaining, TimeUnit.NANOSECONDS);
          if (item == null) break;
          batch.add(item);
        }
        synchronized (lifecycle) { lifecycle.notifyAll(); }
        long start = System.nanoTime(), inserted = 0, bytes = 0, deleted = 0;
        try {
          for (var item : batch) {
            for (var row : item.appends()) {
              insert.setString(1, row.id());
              insert.setBytes(2, row.payload());
              insert.addBatch();
              inserted++;
              bytes += row.payload().length;
            }
            for (var row : item.deletes()) {
              delete.setString(1, row.id());
              delete.addBatch();
            }
          }
          insert.executeBatch();
          for (int count : delete.executeBatch()) {
            if (count < 0) throw new SQLException("SQLite did not report an exact delete count");
            deleted += count;
          }
          connection.commit();
        } catch (Throwable error) {
          try { connection.rollback(); }
          catch (SQLException rollbackError) { error.addSuppressed(rollbackError); }
          throw error;
        } finally { transactions.record(System.nanoTime() - start); }
        pendingRows.addAndGet(inserted - deleted);
        committed.addAndGet(inserted);
        committedBytes.addAndGet(bytes);
        maximumAppendBatch.accumulateAndGet(inserted, Math::max);
        for (var item : batch) item.durable().complete(null);
        batch.clear();
      }
    } catch (Throwable error) {
      synchronized (lifecycle) {
        failure = error;
        for (var item : batch) item.durable().completeExceptionally(error);
        Pending item;
        while ((item = queue.poll()) != null) item.durable().completeExceptionally(error);
        lifecycle.notifyAll();
      }
    }
  }

  synchronized List<OutboxRow> read(int limit) throws SQLException {
    if (limit <= 0) throw new IllegalArgumentException("limit must be positive");
    try (var sql = reader.prepareStatement("SELECT id,payload FROM outbox ORDER BY seq LIMIT ?")) {
      sql.setInt(1, limit);
      var rows = new ArrayList<OutboxRow>();
      try (var result = sql.executeQuery()) {
        while (result.next()) rows.add(new OutboxRow(result.getString(1), result.getBytes(2)));
      }
      return rows;
    }
  }

  void confirmed(List<OutboxRow> rows) {
    if (rows.isEmpty()) throw new IllegalArgumentException("Confirmed batch must not be empty");
    submit(new Pending(List.of(), List.copyOf(rows), new CompletableFuture<>()));
  }

  long pending() { return pendingRows.get(); }
  int queued() { return queue.size(); }
  boolean healthy() { return failure == null && writer.isAlive(); }

  public void close() throws Exception {
    synchronized (lifecycle) { running = false; lifecycle.notifyAll(); }
    writer.join(30000);
    if (writer.isAlive()) throw new IllegalStateException("Outbox drain timed out");
    synchronized (this) { reader.close(); }
  }
}
