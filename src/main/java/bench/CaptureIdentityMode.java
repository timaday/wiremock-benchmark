package bench;

/**
 * Responsibility: enumerate explicit capture selection/identity modes.
 * Must not: infer a mode from request contents. Contract: docs/CONTRACT.md.
 */
enum CaptureIdentityMode { BENCHMARK_HEADERS, STUB_JSON }
