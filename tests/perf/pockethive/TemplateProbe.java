import com.fasterxml.jackson.databind.ObjectMapper;
import io.pockethive.templating.PebbleTemplateRenderer;
import io.pockethive.work.api.WorkItem;
import io.pockethive.work.api.WorkerInfo;
import io.pockethive.templating.api.DisabledSequenceAccess;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;

/** Checks exact body rendering and extraction of actual request/response evidence. */
class TemplateProbe {
    public static void main(String[] args) throws Exception {
        var mapper = new ObjectMapper();
        var scenario = mapper.readTree(Files.readString(Path.of(args[0])));
        var bees = scenario.get("template").get("bees");
        String requestTemplate = bees.get(0).get("config").get("message").get("body").asText();
        String evidenceTemplate = bees.get(8).get("config").get("interceptors").get("templating").get("template").asText();
        var renderer = new PebbleTemplateRenderer(DisabledSequenceAccess.INSTANCE);
        var info = new WorkerInfo("probe", "probe", "probe", null, null);
        var payload = new java.util.HashMap<String, String>();
        payload.put("benchId", "0123456789abcdef-000000000001");
        payload.put("sequence", "0000000001");
        String id = renderer.render(bees.get(0).get("config").get("message").get("headers")
            .get("X-Bench-Id").asText(), Map.of("payloadAsJson", payload));
        if (id.length() != 29) throw new AssertionError("Incorrect ID width");
        int checks = 0;
        for (int size : new int[]{1024, 5120, 10240, 51200}) {
            payload.put("size", Integer.toString(size));
            String requestBody = renderer.render(requestTemplate, Map.of("payloadAsJson", payload));
            if (requestBody.getBytes(StandardCharsets.UTF_8).length != size
                    || !mapper.readTree(requestBody).get("id").asText().equals(id)) {
                throw new AssertionError("Incorrect request body at size " + size);
            }
            var request = Map.of("kind", "http.request", "request", Map.of(
                "body", requestBody, "headers", Map.of("X-Bench-Id", id,
                "X-Bench-Offered-At", "2026-09-29T00:00:00Z")));
            for (String responseBody : new String[]{"x".repeat(size), "corrupt", ""}) {
                var result = Map.of("request", Map.of("path", "/bench/static-" + size + "-6000"),
                    "outcome", Map.of("status", 200, "type", "http_response", "body", responseBody),
                    "metrics", Map.of("durationMs", 6005));
                var item = WorkItem.text(info, "{}").build()
                    .addStepPayload(info, mapper.writeValueAsString(request))
                    .addStepPayload(info, mapper.writeValueAsString(result));
                String rendered = renderer.render(evidenceTemplate,
                    new java.util.HashMap<>(Map.of("payload", result, "workItem", item)));
                var record = mapper.readTree(rendered);
                if (!record.get("bench_id").asText().equals(id)
                        || !record.get("request_sha256").asText().equals(hash(requestBody))
                        || !record.get("response_sha256").asText().equals(hash(responseBody))
                        || record.get("status").asInt() != 200) {
                    throw new AssertionError("Evidence must describe actual payload bytes: " + rendered);
                }
                checks++;
            }
        }
        System.out.println("PASS: " + checks + " actual-payload evidence checks across four sizes.");
    }

    private static String hash(String value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
            .digest(value.getBytes(StandardCharsets.UTF_8)));
    }
}
