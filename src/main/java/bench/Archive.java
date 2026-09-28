package bench;

import com.rabbitmq.client.*;
import java.io.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;

/** External consumer; durably archives full compressed captures before acknowledging RabbitMQ. */
public final class Archive {
  public static void main(String[] args) throws Exception {
    Class.forName("org.sqlite.JDBC");
    Path path = Path.of(Settings.required("ARCHIVE_PATH"));
    Files.createDirectories(path.getParent());
    try (var db = DriverManager.getConnection("jdbc:sqlite:" + path)) {
      try (var sql = db.createStatement()) {
        sql.execute("PRAGMA journal_mode=WAL");
        sql.execute("PRAGMA synchronous=FULL");
        sql.execute("PRAGMA busy_timeout=30000");
        sql.execute(
            "CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,run_id TEXT,request_id"
                + " TEXT,phase TEXT,body_bytes INTEGER,body_sha256 TEXT,payload_zlib BLOB)");
        sql.execute("CREATE INDEX IF NOT EXISTS events_request ON events(run_id,request_id,phase)");
      }
      db.setAutoCommit(false);
      while (true) {
        try (var connection = RabbitPublisher.factory().newConnection("benchmark-archive");
            var channel = connection.createChannel();
            var insert =
                db.prepareStatement("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)")) {
          RabbitPublisher.declare(channel);
          channel.basicQos(512);
          var queue = new ArrayBlockingQueue<Delivery>(512);
          channel.basicConsume(
              Settings.required("RABBIT_QUEUE"),
              false,
              (tag, message) -> {
                try {
                  queue.put(message);
                } catch (InterruptedException e) {
                  Thread.currentThread().interrupt();
                  throw new IOException(e);
                }
              },
              tag -> {});
          while (connection.isOpen()) {
            var first = queue.poll(1, TimeUnit.SECONDS);
            if (first == null) continue;
            var batch = new ArrayList<Delivery>();
            batch.add(first);
            queue.drainTo(batch, 255);
            for (var message : batch) {
              if (!CaptureCodec.CONTENT_TYPE.equals(message.getProperties().getContentType())
                  || !CaptureCodec.CONTENT_ENCODING.equals(
                      message.getProperties().getContentEncoding()))
                throw new IOException("Unexpected capture encoding");
              var event = CaptureCodec.decode(message.getBody());
              byte[] body = Base64.getDecoder().decode(event.bodyBase64());
              insert.setString(1, event.eventId());
              insert.setString(2, event.runId());
              insert.setString(3, event.requestId());
              insert.setString(4, event.phase().name());
              insert.setInt(5, body.length);
              insert.setString(
                  6,
                  HexFormat.of()
                      .formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(body)));
              insert.setBytes(7, message.getBody());
              insert.addBatch();
            }
            insert.executeBatch();
            db.commit();
            channel.basicAck(batch.get(batch.size() - 1).getEnvelope().getDeliveryTag(), true);
          }
        } catch (Exception e) {
          db.rollback();
          System.err.println(
              "Archive connection interrupted; unacknowledged events will be redelivered");
          Thread.sleep(1000);
        }
      }
    }
  }
}
