package bench.load;

import io.gatling.javaapi.core.Simulation;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;
import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

/**
 * Responsibility: generate header-free open arrivals and check empty delayed responses.
 * Must not: provision infrastructure or calculate capture reconciliation.
 * Contract: tests/perf/gatling/DYNAMIC.md; required demo.* system properties.
 */
public final class DynamicCaptureSimulation extends Simulation {
    private final Path output = Path.of(required("output"));
    private final DynamicCaptureJournal journal;
    private final int[] sizes = {1024, 5120, 10240, 51200};

    private static String required(String key) {
        String value = System.getProperty("demo." + key);
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing demo." + key);
        return value;
    }

    @Override public void before() {
        try { Files.writeString(output.resolve("started-ms.txt"), Long.toString(System.currentTimeMillis())); }
        catch (java.io.IOException e) { throw new java.io.UncheckedIOException(e); }
    }

    @Override public void after() {
        try { journal.close(); }
        catch (java.io.IOException e) { throw new java.io.UncheckedIOException(e); }
    }

    public DynamicCaptureSimulation() throws Exception {
        journal = new DynamicCaptureJournal(output);
        String run = required("run"), field = required("field");
        if (!field.equals("correlationId") && !field.equals("requestId"))
            throw new IllegalArgumentException("Explicit supported request field required");
        double rate = Double.parseDouble(required("rate"));
        int ramp = Integer.parseInt(required("ramp"));
        int steady = Integer.parseInt(required("steady"));
        int delayMs = Integer.parseInt(required("delayMs"));
        if (delayMs != 1000 && delayMs != 6000)
            throw new IllegalArgumentException("Delay must be 1000 or 6000 ms");
        var sequence = new AtomicLong();
        var protocol = http.baseUrl(required("url")).shareConnections().disableCaching()
                .disableFollowRedirect().disableWarmUp().contentTypeHeader("application/json")
                .acceptEncodingHeader("identity");
        var requests = scenario("empty 200 dynamic capture").exec(session -> {
            long n = sequence.getAndIncrement();
            String id = run + "-" + n;
            String prefix = "{\"" + field + "\":\"" + id + "\",\"padding\":\"";
            byte[] body = (prefix + "x".repeat(sizes[(int) (n % sizes.length)] - prefix.length() - 2)
                    + "\"}").getBytes(StandardCharsets.UTF_8);
            return session.set("id", id).set("body", body).set("started", System.currentTimeMillis());
        }).exec(http("empty 200").post("/transaction").requestTimeout(Duration.ofSeconds(30))
                .body(InputStreamBody(s -> new java.io.ByteArrayInputStream(s.get("body"))))
                .check(status().is(200), bodyBytes().saveAs("response"), bodyString().is(""),
                        responseTimeInMillis().saveAs("elapsed"), responseTimeInMillis().gte(delayMs - 2)))
                .exec(session -> {
                    byte[] response = session.contains("response") ? session.get("response") : new byte[0];
                    long elapsed = session.contains("elapsed") ? session.getInt("elapsed")
                            : System.currentTimeMillis() - session.getLong("started");
                    journal.record(session.getString("id"), session.getLong("started"), elapsed,
                            !session.isFailed(), session.get("body"), response);
                    return session;
                });
        if (ramp > 0) setUp(requests.injectOpen(rampUsersPerSec(1).to(rate).during(ramp),
                constantUsersPerSec(rate).during(steady))).protocols(protocol)
                .assertions(global().failedRequests().count().is(0L));
        else setUp(requests.injectOpen(constantUsersPerSec(rate).during(steady)))
                .protocols(protocol).assertions(global().failedRequests().count().is(0L));
    }
}
