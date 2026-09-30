import com.fasterxml.jackson.databind.ObjectMapper;
import io.pockethive.templating.PebbleTemplateRenderer;
import io.pockethive.observability.*;
import io.pockethive.work.api.WorkItem;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;

/** Executes the actual result template with PocketHive's renderer and observability model. */
public final class TimingTemplateProbe {
  public static void main(String[] args) throws Exception {
    var mapper = new ObjectMapper();
    var request = Map.of("request", Map.of("headers", Map.of("X-Bench-Id", "0123456789abcdef-000000000000",
        "X-Bench-Offered-At", "2026-09-30T00:00:01Z"), "body", "request body"));
    var result = Map.of("outcome", Map.of("status", 200, "type", "http_response", "body", "response body"),
        "request", Map.of("path", "/bench/static-1024-6000"), "metrics", Map.of("durationMs", 6001, "connectionLatencyMs", 4));
    var observability = new ObservabilityContext();
    observability.setHops(new ArrayList<>(List.of(
        new Hop("generator-0", "g", Instant.parse("2026-09-30T00:00:00Z"), Instant.parse("2026-09-30T00:00:01Z")),
        new Hop("processor-0", "p", Instant.parse("2026-09-30T00:00:02Z"), Instant.parse("2026-09-30T00:00:09Z")),
        new Hop("evidence", "e", Instant.parse("2026-09-30T00:00:10Z"), null))));
    var item = WorkItem.text("{}").observabilityContext(observability).build()
        .addStep(mapper.writeValueAsString(request), Map.of())
        .addStep(mapper.writeValueAsString(result), Map.of());
    var actual = mapper.readTree(new PebbleTemplateRenderer(new io.pockethive.templating.api.SequenceAccess() {
      public String next(String a, String b, String c, long d, long e) { throw new AssertionError("No sequence access expected"); }
      public boolean reset(String key) { throw new AssertionError("No sequence access expected"); }
    }).render(Files.readString(Path.of(args[0])),
        new HashMap<>(Map.of("workItem", item, "payload", result))));
    if (actual.path("hops").size() != 3 || !actual.path("hops").get(2).path("processed_at").isNull()
        || !actual.path("hops").get(1).path("processed_at").asText().equals("2026-09-30T00:00:09Z")
        || actual.path("processor_pacing_ms").asInt() != 4
        || actual.path("http_header_duration_ms").asInt() != 6001
        || actual.path("request_sha256").asText().length() != 64
        || actual.path("response_sha256").asText().length() != 64)
      throw new AssertionError(actual.toString());
    System.out.println("PASS: real PocketHive template records processor hops, null active hop, pacing, headers and body hashes");
  }
}
