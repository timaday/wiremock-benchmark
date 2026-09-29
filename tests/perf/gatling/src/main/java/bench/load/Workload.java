package bench.load;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.ArrayList;

/**
 * Responsibility: materialize exact byte payloads from the selected canonical catalogue.
 * Must not: choose filters, pace arrivals or record outcomes.
 * Contract: docs/CONTRACT.md, workloads and request identity.
 */
public record Workload(String id, int size, int delay, String template, String example) {
    public static List<Workload> read(Path path) throws IOException {
        var result = new ArrayList<Workload>();
        for (var node : new ObjectMapper().readTree(path.toFile())) {
            var value = new Workload(node.required("id").asText(), node.required("size").asInt(),
                    node.required("delay").asInt(), node.required("template").asText(),
                    node.required("example").asText());
            if (!value.id.matches("[a-zA-Z0-9-]+") || value.size < 64 || value.delay < 0
                    || !List.of("static", "json", "text").contains(value.template)
                    || value.example.getBytes(StandardCharsets.UTF_8).length != value.size) {
                throw new IllegalArgumentException("Invalid selected workload: " + value.id);
            }
            result.add(value);
        }
        if (result.isEmpty()) throw new IllegalArgumentException("Empty selected catalogue");
        return List.copyOf(result);
    }

    public String requestId(String run, int slot, long sequence) {
        if (sequence < 0 || sequence > 9_999_999_999L) {
            throw new IllegalArgumentException("Request sequence overflow");
        }
        return run + "-" + String.format(java.util.Locale.ROOT, "%02d%010d", slot, sequence);
    }

    public byte[] request(String requestId) {
        String prefix = "{\"id\":\"" + requestId + "\",\"padding\":\"";
        return (prefix + "x".repeat(size - prefix.length() - 2) + "\"}")
                .getBytes(StandardCharsets.UTF_8);
    }

    public String expected(String requestId) {
        return template.equals("static") ? example : example.replace("0".repeat(29), requestId);
    }
}
