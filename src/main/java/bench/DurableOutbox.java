package bench;

import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** Owns SQLite outbox writes and confirmed deletion. No RabbitMQ or WireMock policy. */
final class DurableOutbox implements AutoCloseable {
  private final Path path;
  private final BlockingQueue<Pending> queue;
  private final Thread writer;
  private volatile boolean running = true;
  private volatile Throwable failure;
  final AtomicLong committed = new AtomicLong();
  final AtomicLong committedBytes = new AtomicLong();

  private record Pending(OutboxRow row, CompletableFuture<Void> durable) {}

  DurableOutbox(Path path, int capacity) throws Exception {
    this.path = path;
    Files.createDirectories(path.toAbsolutePath().getParent());
    Class.forName("org.sqlite.JDBC");
    try (var connection = connect();
        var sql = connection.createStatement()) {
      sql.execute(
          "CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE"
              + " NOT NULL, payload BLOB NOT NULL)");
    }
    queue = new ArrayBlockingQueue<>(capacity);
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
    }
    return connection;
  }

  void append(String id, byte[] bytes) {
    if (!running || failure != null) throw new IllegalStateException("Outbox unavailable", failure);
    var pending = new Pending(new OutboxRow(id, bytes), new CompletableFuture<>());
    try {
      while (!queue.offer(pending, 100, TimeUnit.MILLISECONDS)) {
        if (failure != null || !running)
          throw new IllegalStateException("Outbox unavailable", failure);
      }
      if (failure != null) pending.durable().completeExceptionally(failure);
      pending.durable().join();
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Capture interrupted", e);
    }
  }

  private void writeLoop() {
    var batch = new ArrayList<Pending>(256);
    try (var connection = connect();
        var insert = connection.prepareStatement("INSERT INTO outbox(id,payload) VALUES(?,?)")) {
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
        for (var item : batch) {
          insert.setString(1, item.row().id());
          insert.setBytes(2, item.row().payload());
          insert.addBatch();
        }
        insert.executeBatch();
        connection.commit();
        for (var item : batch) {
          committed.incrementAndGet();
          committedBytes.addAndGet(item.row().payload().length);
          item.durable().complete(null);
        }
        batch.clear();
      }
    } catch (Throwable e) {
      failure = e;
      for (var item : batch) item.durable().completeExceptionally(e);
      Pending item;
      while ((item = queue.poll()) != null) item.durable().completeExceptionally(e);
    }
  }

  List<OutboxRow> read(int limit) throws SQLException {
    try (var connection = connect();
        var sql =
            connection.prepareStatement("SELECT id,payload FROM outbox ORDER BY seq LIMIT ?")) {
      sql.setInt(1, limit);
      var rows = new ArrayList<OutboxRow>();
      try (var result = sql.executeQuery()) {
        while (result.next()) rows.add(new OutboxRow(result.getString(1), result.getBytes(2)));
      }
      return rows;
    }
  }

  void confirmed(List<OutboxRow> rows) throws SQLException {
    try (var connection = connect();
        var sql = connection.prepareStatement("DELETE FROM outbox WHERE id=?")) {
      connection.setAutoCommit(false);
      for (var row : rows) {
        sql.setString(1, row.id());
        sql.addBatch();
      }
      sql.executeBatch();
      connection.commit();
    }
  }

  long pending() throws SQLException {
    try (var connection = connect();
        var sql = connection.createStatement();
        var result = sql.executeQuery("SELECT count(*) FROM outbox")) {
      result.next();
      return result.getLong(1);
    }
  }

  boolean healthy() {
    return failure == null && writer.isAlive();
  }

  public void close() throws Exception {
    running = false;
    writer.join(30000);
    if (writer.isAlive()) throw new IllegalStateException("Outbox drain timed out");
  }
}
