# Engineering evidence, 2026-09-25

- WireMock recommends asynchronous responses for delay performance:
  https://wiremock.org/docs/configuration/
- ServeEventListener lifecycle and intended telemetry role:
  https://wiremock.org/docs/extensibility/listening-for-serve-events/
  Pinned AbstractRequestHandler source shows response snapshot completion before
  beforeResponseSent; response preparation is distinct from delivery completion:
  https://github.com/wiremock/wiremock/blob/3.13.2/src/main/java/com/github/tomakehurst/wiremock/http/AbstractRequestHandler.java
- Official image extension loading: https://wiremock.org/docs/standalone/docker/
- OpenJDK27 GA: https://jdk.java.net/27/ (build35, checksum-verified per architecture).
  Temurin27 image was unavailable during initial setup; this project explicitly
  selects upstream OpenJDK27, not a silent runtime version substitution.
- Publisher confirms: https://www.rabbitmq.com/tutorials/tutorial-seven-java
  Batch confirms keep broker IO away from request handling. Confirmation loss can
  cause duplicate delivery; stable IDs are required.
- SQLite WAL and FULL durability: https://www.sqlite.org/wal.html and
  https://www.sqlite.org/pragma.html#pragma_synchronous
- JMeter throughput timers do not create concurrency:
  https://jmeter.apache.org/usermanual/component_reference.html#Constant_Throughput_Timer
  At1000/s with6s delay, about6000 simultaneous requests are necessary before
  headroom. Insufficient injector capacity is not a server capacity result.
- PocketHive-main/tests/perf/http-mocks inspected for prior context: async tuning,
  pinned image/runtime evidence, correctness oracles, delay-adjusted reporting,
  separate warmup/drain and generator saturation were retained as principles.
  This repository is independent and uses JMeter, not a copied k6 adapter.

- JMeter 5.6.3 Precise Throughput Timer uses a shared schedule with reusable
  clients and finite schedule blocks:
  https://jmeter.apache.org/usermanual/component_reference.html#Precise_Throughput_Timer
  Its documentation warns to verify high-rate operation. The retained 1,000/s
  baseline is the experiment, not an assumption. Open Model 5.6.3 creates new
  JMeterThread instances; our observed one-connection-per-request experiment
  exhausted injector ephemeral ports. No host TCP tuning masks that failure.

- Final pacing mode: `ConstantThroughputTimer.Mode.AllActiveThreadsInCurrentThreadGroup`
  (ordinal 2) multiplies per-request time by the thread count before rounding.
  A late client resets `previousTime` to the current time. These two source facts
  avoid the observed shared-timer ceiling and global schedule catch-up:
  https://github.com/apache/jmeter/blob/rel/v5.6.3/src/components/src/main/java/org/apache/jmeter/timers/ConstantThroughputTimer.java
