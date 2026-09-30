package bench;

import java.lang.management.ManagementFactory;

/**
 * Responsibility: expose JVM/process management-bean measurements as Prometheus text.
 * Must not: infer container RSS, collect request data, or modify JVM settings.
 * Contract: docs/PORTAINER.md, telemetry contract.
 */
final class JvmMetrics {
  static String exposition() {
    var out = new StringBuilder();
    var memory = ManagementFactory.getMemoryMXBean();
    var heap = memory.getHeapMemoryUsage();
    HttpMetrics.metric(out, "wiremock_jvm_heap_used_bytes", "gauge", heap.getUsed());
    HttpMetrics.metric(out, "wiremock_jvm_heap_committed_bytes", "gauge", heap.getCommitted());
    HttpMetrics.metric(out, "wiremock_jvm_heap_max_bytes", "gauge", heap.getMax());
    HttpMetrics.metric(out, "wiremock_jvm_nonheap_used_bytes", "gauge", memory.getNonHeapMemoryUsage().getUsed());
    HttpMetrics.metric(out, "wiremock_jvm_threads", "gauge", ManagementFactory.getThreadMXBean().getThreadCount());
    var os = (com.sun.management.OperatingSystemMXBean) ManagementFactory.getOperatingSystemMXBean();
    HttpMetrics.metric(out, "wiremock_process_cpu_seconds_total", "counter", os.getProcessCpuTime() / 1e9);
    HttpMetrics.metric(out, "wiremock_process_start_time_seconds", "gauge", ManagementFactory.getRuntimeMXBean().getStartTime() / 1000.0);
    long count = 0, millis = 0;
    boolean available = true;
    for (var gc : ManagementFactory.getGarbageCollectorMXBeans()) {
      available &= gc.getCollectionCount() >= 0 && gc.getCollectionTime() >= 0;
      count += gc.getCollectionCount();
      millis += gc.getCollectionTime();
    }
    HttpMetrics.metric(out, "wiremock_jvm_gc_collections_total", "counter", available ? count : Double.NaN);
    HttpMetrics.metric(out, "wiremock_jvm_gc_seconds_total", "counter", available ? millis / 1000.0 : Double.NaN);
    return out.toString();
  }
}
