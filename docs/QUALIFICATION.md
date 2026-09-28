# Qualification on this machine

The subsequent user-requested mixed-hour repeats are tracked in
[REPEAT-QUALIFICATION.md](REPEAT-QUALIFICATION.md).

Status: **both runtimes pass the one-hour mixed workload with durable capture.**
All results below use four JMeter engines on this single Linux x86-64 host.
The declared stimulus is 1,020 requests/s, with a 1,000 successful responses/s
pass target. No failed minute is averaged into a pass.

| Runtime | Capture | Workload | Measured hold | Successful responses/s | HTTP errors | Reconciled events | Result |
|---|---|---|---:|---:|---:|---:|---|
| Official image, Java 17 | On | 50 KiB / 6s / dynamic JSON | 120s | 1,015.25 | 0 | 366,429 / 366,429 | Pass |
| Embedded, Java 27 | On | 50 KiB / 6s / dynamic JSON | 120s | 1,017.07 | 0 | 368,505 / 368,505 | Pass |
| Official image, Java 17 | Off | Mixed 84 cases | 120s | 1,022.84 | 0 | Disabled | Pass |
| Embedded, Java 27 | Off | Mixed 84 cases | 120s | 1,022.44 | 0 | Disabled | Pass |
| Official image, Java 17 | On | Mixed 84 cases | 3,600s | 1,020.14 | 0 | 11,019,456 / 11,019,456 | Pass |
| Embedded, Java 27 | On | Mixed 84 cases | 3,600s | 1,020.14 | 0 | 11,019,303 / 11,019,303 | Pass |

Run IDs: `f5a87f8174da41a1` (official), `7494caba23f54fcd` (headless).
Raw JTL, per-minute verdicts, source fingerprints, container/task inspection,
telemetry and full durable archives remain under `results/` and `state/`.
Compact run summaries in [evidence/](evidence/) preserve verdicts, per-minute
rates, image IDs and source fingerprints without committing the large archives.

Mixed baseline IDs: `f24b2d2064f84b89` (official) and `49c6897749124196`
(headless). Official hour: `e1a567c274974dee`, with 3,673,152 measured request
starts and all 60 minutes above target; minimum delivered rate was 1,017.7/s.
Delay-adjusted p50/p95/p99 were 25/45/63ms (maximum 221ms). No OOM, restart,
missing/corrupt exchange or undrained outbox occurred.

Headless hour: `64a961b1b97f454f`, with 3,673,101 measured request starts and
all 60 minutes above target; minimum delivered rate was 1,018/s. Delay-adjusted
p50/p95/p99 were 25/45/65ms (maximum 160ms). No OOM, restart, missing/corrupt
exchange or undrained outbox occurred. Neither hour required a broker reconnect.

Both mixed hooks-off baselines had a delay-adjusted p95 of 2ms; the capture-on
hours had 45ms. Durable capture therefore has measurable latency cost while
retaining the required throughput in these experiments. These are individual
runs of different durations, not a statistical claim that the two JVMs have
identical performance.

During the measured hours, sampled outbox backlog peaked at 1,857 events
(official) and 1,690 (headless), then drained to zero. Sampled mock heap use
remained within the declared 3 GiB cap. The full per-minute and resource evidence
is retained in the compact JSON summaries.

Both runtimes also pass the separate small broker-outage/process-kill recovery
proof, including full request/response body comparison after replay:
`fault-57016c0e00894377` and `fault-0074aec89e5d4496` respectively.
These recovery tests are functional proofs, not throughput qualification during
an extended broker outage.

Continuous-mode shutdown also passes: `9bac1d0245ef4a59`, official image,
100/s target with a declared 104/s stimulus. A SIGINT (Ctrl+C) stopped the same
four running engines after 91.652 measured seconds. They drained successfully:
104.30 successful responses/s, zero errors, and 28,641/28,641 capture events
reconciled. This proves the stop/drain path, not indefinite uptime.

## Scope of the evidence

- Host: 20 logical CPUs, approximately 30.8 GiB RAM, shared with other applications.
  The specifically authorised PocketHive manual-test stack is paused during load.
- Mock: 4 CPU / 4 GiB container / 3 GiB heap. Each engine: 2 CPU / 1.75 GiB
  container / 1 GiB heap. RabbitMQ: 2 CPU / 1.5 GiB. Archive: 2 CPU / 768 MiB.
- Official WireMock 3.13.2 runs its supplied Java `17.0.19+10`; embedded 3.13.2
  runs OpenJDK `27+35-2325`. Both are containerised and use the same extension.
  This comparison does not isolate container overhead from JVM/launcher changes.
- HTTP request and response bodies are both the stated size, uncompressed.
  Capture envelopes are compressed losslessly; the deterministic `x` padding
  is highly compressible. Do not generalise capture disk/CPU capacity to random
  or already-compressed bodies without another experiment.
- The mixed workload covers 84 size/template/delay combinations. A mixed hold
  does not prove each individual combination at 1,000/s for an hour.
- Multi-host Swarm, ARM64, Windows/macOS Docker Desktop and direct native Java
  launch remain unqualified. The recipes are provided for repeatable testing.
- A finite hold cannot prove indefinite uptime. Continuous mode must be stopped
  and reconciled before its observed interval can receive a verdict.

Validation also passed 14 Python tests, four Java tests in the image build,
Python formatting, and Compose configuration validation. See
[verification.json](evidence/verification.json).

After the headless verdict passed, Docker's aggregate service-log export hung.
The log-reader process was terminated and owned services were cleaned up;
per-engine JTL, JMeter and GC logs remain retained. The final runner bounds this
optional export to 30s, records/reports incomplete diagnostics, and still cleans
up. Focused regression tests cover the timeout and cleanup. This change affects
post-run diagnostics only; it does not change the measured workload or gates.

Earlier failed sizing and pacing experiments remain retained and are described
in [the build record](BUILD-RECORD.md). See [the contract](CONTRACT.md) for exact
durability boundaries and acceptance criteria.

The paused PocketHive manual-test stack has been restored: 19 containers running,
all configured health checks passing, and HTTP 200 on port 18089. Owned benchmark
services and overlays are removed; the local-only Swarm manager remains available.
