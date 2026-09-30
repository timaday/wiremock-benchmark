# PocketHive one-hour WireMock comparison — September 30, 2026

Both runtimes passed a full 3,600-second measured hold with six-second responses,
mixed 1/5/10/50 KiB request and response bodies, and static/JSON/text templates.
Each completed all 3,763,800 requests and reconciled 11,291,400 capture events.
Every measured minute exceeded 1,000 server completions/s. Sampled heap and
container memory remained bounded; neither runtime had a full GC, OOM or restart.

| Measurement | Official / Java 17 | Headless / Java 27 |
| --- | ---: | ---: |
| Measured hold | 3,600 s | 3,600 s |
| Offered requests/s | 1020.000 | 1020.000 |
| Server completions/s | 1019.996 | 1020.015 |
| Lowest minute completions/s | 1017.867 | 1017.850 |
| Missing / duplicate / bad status / bad body | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| HTTP response-header p99 | 6.117 s | 6.184 s |
| PocketHive pipeline p99 | 8.160 s | 11.617 s |
| Mean WireMock CPU cores | 0.972 | 1.094 |
| Peak sampled container memory | 3.350 GiB | 2.807 GiB |
| Sampled JVM heap range | 1360–2488 MiB | 1296–2111 MiB |
| Settled early / final memory median | 3.340 / 3.345 GiB | 2.452 / 2.208 GiB |
| Longest GC pause | 61.719 ms | 54.553 ms |
| Full GC / OOM / restart | 0 / 0 / 0 | 0 / 0 / 0 |
| Mean PocketHive CPU cores | 2.906 | 2.906 |
| Mean / peak PocketHive memory | 9.024 / 9.614 GiB | 9.083 / 9.761 GiB |

Rates use one common 3,600-second interval per runtime, starting 60 seconds after
the latest lane's first arrival. All four lanes continued beyond that window.
Latency percentiles cover all arrivals, including warmup and tail. HTTP timing
ends at response headers and excludes body reading. Pipeline timing includes
queueing, HTTP and evidence processing; it must not be labelled full HTTP latency.

Resource summaries each contain 358 samples with zero sampling errors. Memory
is Docker-reported usage, not separately measured RSS. Early memory medians use
minutes 5–15; final medians use minutes 50–60. PocketHive figures sum nine workers
and their controller, excluding shared brokers, ingress and other platform services.
This workload therefore has significant injector overhead: about 9 GiB and 2.9 CPU
cores, before shared infrastructure. Worker JVM heap/GC were not separately measured.

The runtimes ran sequentially once on a shared host already using swap. Both use
WireMock 3.13.2, but official runs Java 17.0.19+10 and headless Java 27+35-2325.
Their differences cannot be attributed solely to the wrapper. This establishes
one-hour behavior for this mixed workload; it does not prove leak freedom,
indefinite stability or each individual case at 1,000 requests/s.

## Payload and template coverage

| Payload | Template | Requests per runtime | Official header p99 | Headless header p99 |
| --- | --- | ---: | ---: | ---: |
| 1 KiB | static | 313,652 | 6117 ms | 6182 ms |
| 1 KiB | json | 313,652 | 6117 ms | 6182 ms |
| 1 KiB | text | 313,652 | 6116 ms | 6181 ms |
| 5 KiB | static | 313,652 | 6117 ms | 6182 ms |
| 5 KiB | json | 313,652 | 6116 ms | 6183 ms |
| 5 KiB | text | 313,652 | 6117 ms | 6182 ms |
| 10 KiB | static | 313,648 | 6118 ms | 6183 ms |
| 10 KiB | json | 313,648 | 6116 ms | 6182 ms |
| 10 KiB | text | 313,648 | 6117 ms | 6182 ms |
| 50 KiB | static | 313,648 | 6118 ms | 6186 ms |
| 50 KiB | json | 313,648 | 6120 ms | 6188 ms |
| 50 KiB | text | 313,648 | 6120 ms | 6189 ms |

## Configuration and evidence

- Four generator/processor lanes at 255 requests/s: 1,020/s offered for a 1,000/s pass target.
- 60 seconds warmup, 3,600 seconds hold, 30 additional seconds of arrivals, then full drain.
- About 6,120 requests concurrently awaiting six-second responses; no 100-request concurrency cap.
- Each processor: 1,800 platform threads, PER_THREAD HTTP connections, 1 GiB heap.
- Each mock: 4 CPU, 4 GiB container limit, 3 GiB heap, durable capture enabled.
- Explicit Artemis work transport and a dedicated persistent Redis result sink.
- PocketHive release 0.15.35, public ingress http://localhost:8088.
- Published bundle source: `2c509f1b35a9298f36f6c3759a234c4461661aa8`.
- Canonical fixture source: `wiremock-benchmark` commit `0b1eb6306c1ab43ec6af85bb6f8d0e3d569de92a` (clean).
- Official bundle/run: `ph-wiremock-official-endurance-eaa015f7` / `eaa015f74e704452`.
- Headless bundle/run: `ph-wiremock-headless-endurance-8a9ee9f1` / `8a9ee9f13a3136c6`.

Exact verdicts, per-minute rates, five-minute memory windows and provenance are in
[evidence-endurance-2026-09-30](evidence-endurance-2026-09-30).
The collectors both exited zero with every expected unique ID and empty Redis lists.
Final capture errors/pending were zero; committed and confirmed were 11,291,400 each.

Raw gzip results, telemetry, GC logs, exact analysis scripts and verifier databases
are retained in Docker volume `wmb-ph-endurance-artifacts` (container mount `/artifacts`).
Full compressed captures remain in `wmb-ph-20260929_archive-data` (`/archive/events.db`).
The artifact container has the benchmark source at `/bench` and canonical fixture tools
at `/canonical/tools`. `stream_verify.py` is the frozen endurance-format analysis
script; `analyze.py` remains the maintained short-profile analyzer. Source hashes are
recorded in `provenance.json`. Use a new scratch `--database` path when repeating:

```sh
python /artifacts/stream_verify.py \
  --bundle /bench/bundles/ph-wiremock-headless-endurance-8a9ee9f1 \
  --results /artifacts/headless-results.jsonl.gz --archive /archive/events.db \
  --metrics /artifacts/headless-final-metrics.json --canonical-repo /canonical \
  --database /artifacts/headless-recheck.sqlite --output /artifacts/headless-recheck.json
```

The bounded-memory verifier reproduced the earlier 91,800-request reference verdict.
Five mutations independently rejected missing IDs, duplicate IDs, corrupt response
hashes, HTTP errors and undrained captures. Both complete endurance verifications
exited zero. Temporary upload capabilities remain in the private `/tmp` run directory;
that directory must not be published wholesale.

## Setup corrections and cleanup

The approved local ingress correction raised `/scenario-manager/` upload size to
16 MB after logs confirmed HTTP 413 for a 2,611,039-byte bundle. Both owner validations
and CREATE publications then succeeded. The applied local Compose overlay is
`/tmp/ph-wiremock-benchmark/endurance/upload-limit.override.yaml`.

The first headless creation hit Scenario Manager direct-buffer exhaustion before
workers started (30,737,715 bytes requested; 157,542,273 allocated; 162,201,600 limit).
Restarting only Scenario Manager restored publication/runtime preparation. Owner
reads reconciled the failed attempt; a new swarm ID and idempotency key created
`ph-wmb-headless-hour-8a9ee9f1-v2`. Failed attempts consumed no workload IDs.
These are separate PocketHive setup issues, not failures of the measured WireMocks.

Both completed swarms were stopped and removed through PocketHive MCP. The owner
reported terminal removal success with no remaining resources; the final swarm list
was empty. Isolated WireMock, RabbitMQ, Redis and archive fixtures are stopped.
Evidence volumes and published scenarios are retained. Fresh IDs are required for
another run. PocketHive remains running on port 8088. These are local development
observations under the local MCP exception, not governed HiveGate execution.

Review scope: benchmark report/evidence only. No runtime interfaces changed in this
closeout. Five verifier mutation checks and both full reconciliations passed.
The portable comparison stack requested next is a separate work unit.
