package bench;

import static org.junit.jupiter.api.Assertions.*;

import com.rabbitmq.client.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Integration checks use only an explicitly selected disposable RabbitMQ test interface. */
@EnabledIfEnvironmentVariable(named = "CAPTURE_TEST_RABBIT_URI", matches = ".+")
class RabbitCaptureBatchTest {
  private Connection connect() throws Exception {
    var factory = new ConnectionFactory();
    factory.setUri(System.getenv("CAPTURE_TEST_RABBIT_URI"));
    factory.setAutomaticRecoveryEnabled(false);
    return factory.newConnection("direct-capture-integration");
  }

  @Test
  void realBrokerRetainsCompletePersistentEnvelopeAndRequiresConsumerAcknowledgement() throws Exception {
    verifyRetention("classic");
  }

  @Test
  void realQuorumQueueRetainsTheSameEnvelope() throws Exception {
    verifyRetention("quorum");
  }

  private void verifyRetention(String type) throws Exception {
    try (var connection = connect(); var channel = connection.createChannel()) {
      String queue = "direct-capture-test-" + UUID.randomUUID();
      channel.queueDeclare(queue, true, false, false, Map.of("x-queue-type", type));
      var transport = new RabbitCaptureBatch(connection, channel, queue);
      byte[] body = new byte[50 * 1024];
      new Random(29).nextBytes(body);
      var event = new CaptureEvent(2, "id", "run", "request", "request", CorrelationStatus.PRESENT, Phase.REQUEST, 123,
          "POST", "/bench/test", 0, Map.of("X-Test", List.of("one", "two")),
          Base64.getEncoder().encodeToString(body));
      transport.publish(List.of(new OutboxRow(event.eventId(), CaptureCodec.encode(event))), 3000);
      try (var consumer = connection.createChannel()) {
        var delivery = consumer.basicGet(queue, false);
        assertNotNull(delivery);
        assertEquals(2, delivery.getProps().getDeliveryMode());
        assertEquals(event.eventId(), delivery.getProps().getMessageId());
        assertEquals(CaptureCodec.CONTENT_TYPE, delivery.getProps().getContentType());
        assertEquals(CaptureCodec.CONTENT_ENCODING, delivery.getProps().getContentEncoding());
        assertEquals(event, CaptureCodec.decode(delivery.getBody()));
        // Closing without ack must make it available to the next consumer.
      }
      try (var consumer = connection.createChannel()) {
        var replay = consumer.basicGet(queue, false);
        assertNotNull(replay);
        assertTrue(replay.getEnvelope().isRedeliver());
        assertEquals(event, CaptureCodec.decode(replay.getBody()));
        consumer.basicAck(replay.getEnvelope().getDeliveryTag(), false);
      }
    }
  }

  @Test
  void realBrokerConfirmForUnroutableMessageIsNotAcceptedAsSuccess() throws Exception {
    try (var connection = connect(); var channel = connection.createChannel()) {
      var transport = new RabbitCaptureBatch(connection, channel, "missing-" + UUID.randomUUID());
      assertThrows(IllegalStateException.class, () -> transport.publish(
          List.of(new OutboxRow("unroutable", new byte[] {1})), 3000));
    }
  }
}
