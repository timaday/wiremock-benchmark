package bench.load;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Map;

/**
 * Responsibility: own admission, response evidence and verified engine completion.
 * Must not: schedule load or infer receipt from expected response bytes.
 * Contract: docs/CONTRACT.md, client CSV and completion counters.
 */
public final class ResultJournal {
    public static final String HEADER = "timeStamp,elapsed,success,bench_id,case_id,delay_ms,payload_bytes,request_sha256,response_sha256";
    private final EngineConfig config;
    private final BufferedWriter writer;
    private long started;
    private long completed;
    private boolean stopping;
    private IOException failure;

    public ResultJournal(EngineConfig config) throws IOException {
        this.config = config;
        writer = Files.newBufferedWriter(config.directory().resolve("engine-" + config.slot() + ".csv"));
        writer.write(HEADER + "\n");
    }

    private boolean shouldStop() {
        stopping |= System.currentTimeMillis() >= config.endMs()
                || Files.exists(config.directory().resolve("stop.requested"));
        return stopping;
    }

    public synchronized boolean admit() {
        if (shouldStop()) return false;
        started++;
        return true;
    }

    public synchronized boolean drained() {
        return shouldStop() && started == completed;
    }

    public static String hash(byte[] body) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public synchronized void record(Workload workload, String id, byte[] request, byte[] response,
                                    long timestamp, long elapsed, boolean httpPassed) {
        boolean correct = httpPassed && elapsed + 2 >= workload.delay()
                && Arrays.equals(response, workload.expected(id).getBytes(StandardCharsets.UTF_8));
        try {
            writer.write(timestamp + "," + elapsed + "," + correct + "," + id + "," + workload.id()
                    + "," + workload.delay() + "," + request.length + "," + hash(request)
                    + "," + hash(response) + "\n");
            completed++;
        } catch (IOException e) {
            failure = e;
            throw new UncheckedIOException(e);
        }
    }

    public synchronized void finish() throws IOException {
        writer.close();
        if (failure != null) throw failure;
        if (started == 0 || started != completed) {
            throw new IllegalStateException("Engine did not complete every admitted request");
        }
        new ObjectMapper().writeValue(config.directory()
                        .resolve("engine-" + config.slot() + "-completion.json").toFile(),
                Map.of("started", started, "completed", completed));
    }
}
