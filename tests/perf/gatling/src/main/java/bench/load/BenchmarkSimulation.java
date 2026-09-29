package bench.load;

import io.gatling.javaapi.core.Simulation;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicLong;
import static io.gatling.javaapi.core.CoreDsl.*;
import static io.gatling.javaapi.http.HttpDsl.*;

/**
 * Responsibility: express the benchmark with Gatling native open arrivals and HTTP checks.
 * Must not: reimplement pacing, provision servers or calculate the aggregate verdict.
 * Contract: docs/CONTRACT.md; selected-cases.json owns workload selection.
 */
public final class BenchmarkSimulation extends Simulation {
    private final EngineConfig config;
    private final ResultJournal journal;

    @Override public void before() { config.awaitBarrier(); }
    @Override public void after() {
        try { journal.finish(); }
        catch (java.io.IOException e) { throw new java.io.UncheckedIOException(e); }
    }

    public BenchmarkSimulation() throws Exception {
        config = EngineConfig.read(System.getenv());
        var cases = Workload.read(config.directory().resolve("selected-cases.json"));
        journal = new ResultJournal(config);
        var sequence = new AtomicLong();
        var protocol = http.baseUrl("http://" + config.host() + ":8080")
                .shareConnections().disableCaching().disableFollowRedirect().disableWarmUp()
                .contentTypeHeader("application/json").acceptEncodingHeader("identity");
        var requests = scenario("benchmark").exec(session -> {
            long n = sequence.getAndIncrement();
            var workload = cases.get((int) (n % cases.size()));
            String id = workload.requestId(config.runId(), config.slot(), n);
            byte[] request = workload.request(id);
            boolean admitted = journal.admit();
            return session.set("admitted", admitted).set("workload", workload)
                    .set("benchId", id).set("request", request)
                    .set("startedMs", System.currentTimeMillis());
        }).exitHereIf(session -> !session.getBoolean("admitted"))
                .exec(http(session -> session.<Workload>get("workload").id())
                        .post(session -> "/bench/" + session.<Workload>get("workload").id())
                        .header("X-Bench-Id", "#{benchId}").header("X-Bench-Run", config.runId())
                        .requestTimeout(Duration.ofSeconds(30))
                        // Consumed streams are non-replayable in Gatling's pooled-connection retry path.
                        .body(InputStreamBody(session -> new java.io.ByteArrayInputStream(session.get("request"))))
                        .check(bodyBytes().saveAs("response"), responseTimeInMillis().saveAs("elapsed"),
                                status().is(200), bodyString().is(session -> session.<Workload>get("workload")
                                        .expected(session.getString("benchId"))),
                                responseTimeInMillis().gte(session -> session.<Workload>get("workload").delay() - 2)))
                .exec(session -> {
                    // A transport failure has no received body/timing check result.
                    byte[] response = session.contains("response") ? session.get("response") : new byte[0];
                    long elapsed = session.contains("elapsed") ? session.getInt("elapsed")
                            : System.currentTimeMillis() - session.getLong("startedMs");
                    journal.record(session.get("workload"), session.getString("benchId"),
                            session.get("request"), response, session.getLong("startedMs"), elapsed,
                            !session.isFailed());
                    return session;
                });
        var control = scenario("drain controller")
                .asLongAs(session -> !journal.drained()).on(pause(Duration.ofMillis(250)))
                .exec(stopLoadGenerator("All admitted requests drained"));
        setUp(requests.injectOpen(constantUsersPerSec(config.rate())
                        .during(Duration.ofMillis(config.endMs() - config.startMs()))),
                control.injectOpen(atOnceUsers(1)))
                .protocols(protocol).assertions(global().failedRequests().count().is(0L));
    }
}
