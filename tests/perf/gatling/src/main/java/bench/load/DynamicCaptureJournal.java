package bench.load;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Responsibility: persist actual client completions for the empty-response demo.
 * Must not: pace requests or infer receipt from server capture callbacks.
 * Contract: tests/perf/gatling/DYNAMIC.md.
 */
public final class DynamicCaptureJournal implements AutoCloseable {
    private final BufferedWriter writer;

    public DynamicCaptureJournal(Path directory) throws IOException {
        writer = Files.newBufferedWriter(directory.resolve("clients.csv"));
        writer.write("id,startedMs,completedMs,elapsedMs,success,bytes,requestSha256,responseSha256\n");
    }

    public synchronized void record(String id, long started, long elapsed, boolean success,
                                    byte[] request, byte[] response) {
        try {
            writer.write(id + "," + started + "," + System.currentTimeMillis() + "," + elapsed
                    + "," + success + "," + request.length + "," + ResultJournal.hash(request)
                    + "," + ResultJournal.hash(response) + "\n");
        } catch (IOException e) { throw new UncheckedIOException(e); }
    }

    @Override public synchronized void close() throws IOException { writer.close(); }
}
