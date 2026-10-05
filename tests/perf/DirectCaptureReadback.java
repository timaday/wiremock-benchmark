package bench;

import com.rabbitmq.client.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/**
 * Responsibility: reconcile a dedicated smoke queue against independent HTTP body hashes.
 * Must not: consume shared work queues or acknowledge before saving complete evidence.
 * Contract: deploy/portainer/smoke.py output and docs/CONTRACT.md capture envelope.
 */
public final class DirectCaptureReadback {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("client-json capture-prefix evidence-json");
    var runs = Json.MAPPER.readTree(Files.readAllBytes(Path.of(args[0])));
    var factory = new ConnectionFactory();
    factory.setUri(System.getenv("CAPTURE_TEST_RABBIT_URI"));
    var records = new ArrayList<CaptureEvent>();
    try (var connection = factory.newConnection("direct-capture-smoke-readback");
         var channel = connection.createChannel()) {
      long lastTag = 0;
      for (var run : runs) {
        String queue = args[1] + "." + run.get("runtime").asText();
        var expected = new HashMap<String, Object>();
        for (var request : run.get("requests")) expected.put(request.get("id").asText(), request);
        var seen = new HashSet<String>();
        GetResponse message;
        while ((message = channel.basicGet(queue, false)) != null) {
          var props = message.getProps();
          require(Integer.valueOf(2).equals(props.getDeliveryMode()), "persistent delivery");
          require(CaptureCodec.CONTENT_TYPE.equals(props.getContentType()), "content type");
          require(CaptureCodec.CONTENT_ENCODING.equals(props.getContentEncoding()), "encoding");
          var event = CaptureCodec.decode(message.getBody());
          require(event.eventId().equals(props.getMessageId()), "AMQP/event identity");
          require(event.runId().equals(run.get("runId").asText()), "run identity");
          require(expected.containsKey(event.requestId()), "unexpected request");
          var request = Json.MAPPER.valueToTree(expected.get(event.requestId()));
          require(seen.add(event.requestId() + ":" + event.phase()), "duplicate request phase");
          require(event.url().equals("/bench/" + request.get("case").asText()), "request URL");
          require(event.method().equals("POST"), "request method");
          byte[] body = Base64.getDecoder().decode(event.bodyBase64());
          if (event.phase() == Phase.SEND_COMPLETED) {
            require(body.length == 0 && event.status() == 200, "completion fields");
          } else {
            require(body.length == request.get("size").asInt(), "full body length");
            String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
            String field = event.phase() == Phase.REQUEST ? "requestSha256" : "responseSha256";
            require(hash.equals(request.get(field).asText()), "client/capture hash");
            require(!event.headers().isEmpty(), "complete application headers");
          }
          records.add(event);
          lastTag = message.getEnvelope().getDeliveryTag();
        }
        require(seen.size() == expected.size() * Phase.values().length, "all request phases");
      }
      try (var evidence = FileChannel.open(Path.of(args[2]), StandardOpenOption.CREATE_NEW,
          StandardOpenOption.WRITE)) {
        var bytes = ByteBuffer.wrap(Json.bytes(records));
        while (bytes.hasRemaining()) evidence.write(bytes);
        evidence.force(true);
      }
      if (lastTag != 0) channel.basicAck(lastTag, true);
    }
    System.out.println("PASS: " + records.size() + " complete captures reconciled and saved before ack");
  }

  private static void require(boolean condition, String description) {
    if (!condition) throw new AssertionError(description);
  }
}
