package bench.load;

import java.nio.file.Path;
import java.util.Map;

/**
 * Responsibility: resolve and validate explicit per-engine settings once.
 * Must not: select workloads or infer missing configuration.
 * Contract: docs/CONTRACT.md, four-engine execution.
 */
public record EngineConfig(String runId, int slot, String host, double rate,
                           long startMs, long endMs, Path directory) {
    public static EngineConfig read(Map<String, String> env) {
        String run = env.get("RUN_ID");
        int slot = Integer.parseInt(env.get("ENGINE_SLOT"));
        double rate = Double.parseDouble(env.get("ENGINE_RATE"));
        long start = Long.parseLong(env.get("LOAD_START_MS"));
        long end = Long.parseLong(env.get("MEASURE_END_MS"));
        String host = env.get("BENCH_HOST");
        if (run == null || !run.matches("[0-9a-f]{16}") || slot < 1 || slot > 4
                || !Double.isFinite(rate) || rate <= 0 || host == null || host.isBlank()
                || start <= 0 || end <= start) {
            throw new IllegalArgumentException("Invalid explicit engine configuration");
        }
        return new EngineConfig(run, slot, host, rate, start, end, Path.of("/results", run));
    }

    public void awaitBarrier() {
        long wait = startMs - System.currentTimeMillis();
        if (wait <= 0) throw new IllegalStateException("Engine missed startup barrier");
        try {
            Thread.sleep(wait);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Engine interrupted before launch", e);
        }
    }
}
