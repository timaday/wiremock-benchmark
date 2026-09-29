package bench.load;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class ResultJournalTest {
    @TempDir Path directory;

    private EngineConfig config() {
        return new EngineConfig("0123456789abcdef", 1, "official", 3,
                System.currentTimeMillis(), System.currentTimeMillis() + 60_000, directory);
    }

    @Test void incompleteAdmissionCannotProduceCompletionRecord() throws Exception {
        var journal = new ResultJournal(config());
        assertTrue(journal.admit());
        assertThrows(IllegalStateException.class, journal::finish);
        assertFalse(Files.exists(directory.resolve("engine-1-completion.json")));
    }

    @Test void stopRefusesNewRequestsButWaitsForActualResponse() throws Exception {
        var journal = new ResultJournal(config());
        var workload = new Workload("text-1024-6000", 1024, 6000, "text", "0".repeat(29) + "x".repeat(995));
        String id = workload.requestId(config().runId(), 1, 0);
        assertTrue(journal.admit());
        Files.createFile(directory.resolve("stop.requested"));
        assertFalse(journal.admit());
        assertFalse(journal.drained());
        journal.record(workload, id, workload.request(id), workload.expected(id).getBytes(StandardCharsets.UTF_8), 1, 6000, true);
        assertTrue(journal.drained());
        journal.finish();
        assertTrue(Files.readString(directory.resolve("engine-1.csv")).contains(",true," + id));
    }

    @Test void corruptedAndMissingResponsesKeepActualHashesAndFail() throws Exception {
        var journal = new ResultJournal(config());
        var workload = new Workload("static-1024-0", 1024, 0, "static", "x".repeat(1024));
        for (byte[] response : new byte[][] {"wrong".getBytes(StandardCharsets.UTF_8), new byte[0]}) {
            assertTrue(journal.admit());
            journal.record(workload, "id", workload.request("id"), response, 1, 1, false);
        }
        journal.finish();
        var rows = Files.readAllLines(directory.resolve("engine-1.csv"));
        assertTrue(rows.get(1).contains(",false,"));
        assertTrue(rows.get(1).endsWith(ResultJournal.hash("wrong".getBytes(StandardCharsets.UTF_8))));
        assertTrue(rows.get(2).endsWith(ResultJournal.hash(new byte[0])));
    }

    @Test void exactSizesAndDisjointEngineIdentities() {
        for (int size : new int[] {1024, 5120, 10240, 51200}) {
            var workload = new Workload("case", size, 0, "text", "0".repeat(29) + "x".repeat(size - 29));
            String a = workload.requestId(config().runId(), 1, 10);
            String b = workload.requestId(config().runId(), 2, 10);
            assertEquals(29, a.length());
            assertNotEquals(a, b);
            assertEquals(size, workload.request(a).length);
            assertEquals(size, workload.expected(a).getBytes(StandardCharsets.UTF_8).length);
        }
    }

    @Test void invalidRateIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> EngineConfig.read(Map.of(
                "RUN_ID", config().runId(), "ENGINE_SLOT", "1", "ENGINE_RATE", "NaN",
                "LOAD_START_MS", "1", "MEASURE_END_MS", "2", "BENCH_HOST", "official")));
    }
}
