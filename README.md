# WireMock durable-capture benchmark

Portable WireMock **3.13.2** comparison: official Docker runtime versus embedded,
headless **OpenJDK 27**, with the same RabbitMQ capture extension in both.
Four Gatling 3.15.1 engines run as Docker Swarm tasks and generate the combined load. MockServer is an optional future comparator.

**A build or smoke pass is not a 1,000 requests/sec qualification.** See the
[historical JMeter qualification report](docs/QUALIFICATION.md), per-run `verdict.json` and
[contract](docs/CONTRACT.md) for measured results, exact gates and scope.

## Portable Portainer / Swarm lab

For a generator-independent deployment of both WireMocks, RabbitMQ, durable archives
and a provisioned Grafana comparison dashboard, use [the Portainer guide](docs/PORTAINER.md).
It includes GHCR images pinned by digest and an explicit existing-PocketHive-broker variant.

For HiveForge v0.5.9, use the [HiveForge lab deployment](docs/HIVEFORGE.md):
the same seven services, public lab credentials and no Docker secrets.

## PocketHive workload bundles

The [PocketHive benchmark package](tests/perf/pockethive/README.md) contains both
completed one-hour bundles, smoke/load profiles, fresh-bundle preparation, result
collection and verification tools, and the measured comparison report. The hour
profile offers 1,020 requests/s with six-second delay across all sizes/templates.
It requires a PocketHive deployment with Artemis work transport and a dedicated
Redis evidence sink; WireMock capture uses RabbitMQ separately.

## Run

Requires Docker Engine/Compose, a local Swarm manager, and Python 3.10+ on a Linux
Docker host (Windows: run inside WSL2). No local Java, Maven, RabbitMQ or Gatling
is needed. Linux x86-64 is the initial test host. Image recipes also select upstream
Linux ARM64 JDK27, but that architecture needs its own qualification. macOS Docker Desktop can use the Linux images and shared bind paths, but has not
been qualified here. Native Windows Python is unsupported by the POSIX suite lock.
Docker VM resources and file sharing affect results.

```sh
# Once, if this machine is not already a Swarm manager (local-only qualification):
docker swarm init --listen-addr 127.0.0.1:2377 --advertise-addr 127.0.0.1

python3 tools/fixtures.py
RUN_NAMESPACE=build CAPTURE_ENABLED=true docker compose --profile official --profile headless --profile tools build

# Small integrated check. Sizes and templates cycle deterministically.
python3 tools/bench.py --mode headless --capture on --target 10 --offered 12 --seconds 30
python3 tools/bench.py --mode official --capture on --target 10 --offered 12 --seconds 30

# Hook overhead: keep the same runtime, case, resources and rate.
python3 tools/bench.py --mode official --capture off --target 1000 --offered 1020 --seconds 120
python3 tools/bench.py --mode official --capture on --target 1000 --offered 1020 --seconds 120

# Hour-long mixed holds, run one mode at a time.
python3 tools/bench.py --mode official --capture on --target 1000 --offered 1020 --seconds 3600
python3 tools/bench.py --mode headless --capture on --target 1000 --offered 1020 --seconds 3600

# Worst delayed body; change target/offered together for the 100/250/500 ladder.
python3 tools/bench.py --mode headless --capture on --target 1000 --offered 1020 --case json-51200-6000 --seconds 300
```

`--offered 1020` explicitly offers 2% headroom for the **1,000/s pass target**;
actual offered/completed rates are reported. Use `--offered 1000` for a strict
1,000/s stimulus; short delivery is a failed target, not rounded into a pass.
For continuous checking, add `--continuous`: the same mock and injector processes
run until Ctrl+C (a one-year scheduler ceiling is explicit). Ctrl+C requests
graceful Gatling stop, drains responses/capture and reports the actual observed
interval. Use `--seconds 86400` for a bounded 24-hour hold. Interrupted setup or
a stop before warmup completes is not a qualification pass.

Workload filters compose; omitting a filter cycles every catalogue value.
Sizes apply equally to request and response. `--case` selects an exact case and
cannot combine with filters.

```sh
# Fixed 10 KiB, varied 0–6s delays, dynamic JSON/text templates:
python3 tools/bench.py --mode official --capture on --size-kib 10 --template json text
# Fixed 6s, mixed 1 and 50 KiB, all templates:
python3 tools/bench.py --mode headless --capture on --delay-ms 6000 --size-kib 1 50
# Everything fixed:
python3 tools/bench.py --mode official --capture on --delay-ms 1000 --size-kib 5 --template json
# Plan a sequential fixed-size qualification across all delays and both runtimes:
python3 tools/qualify.py --size-kib 10 --template json text
```

Supported delays: **0, 1, 1.5, 2, 3, 4, 5, 6 seconds** (`--delay-ms` uses milliseconds).
Fixtures contain 96 combinations: 1/5/10/50KiB request and response, three response
templates, eight delays from 0–6s. `--case mixed` cycles all combinations. Individual
case runs isolate a maximum; a mixed pass does not prove every case at the full rate.
The Java simulation lives in `tests/perf/gatling/` and uses Gatling’s native
`constantUsersPerSec` open-arrival scheduler with shared HTTP connections. Injector starvation, HTTP failures, capture mismatch and failed minute
targets make the runner return nonzero. No dashboard listener runs under load.

## Capture and durability

REQUEST, RESPONSE_PREPARED and SEND_COMPLETED records preserve WireMock's
application headers, complete bodies and correlation. A SQLite FULL/WAL commit
precedes each hook's completion. Capture envelopes use
lossless zlib compression before persistence and RabbitMQ transport; HTTP payloads
remain uncompressed. RabbitMQ
publication is batched on a separate thread; confirmed persistent messages can
leave the outbox. Outages retain committed outbox data. The archive consumer saves
full zlib-compressed events in SQLite **before acknowledging** RabbitMQ. Event IDs
deduplicate uncertain republishing. Archive SHA-256 hashes reconcile every measured
request/response against the client's actual bytes, not just aggregate counters.

Lossless capture has an unavoidable synchronous disk cost. This benchmark measures
whether throughput stays above target despite that cost; it does not promise zero
CPU, memory or latency overhead. Finite disk cannot absorb an infinite outage.
A capture storage failure terminates the owned mock process and fails the run.
See [durability boundaries](docs/CONTRACT.md#durable-capture), especially prepared
response versus actual client delivery and requests interrupted before commit.

## Evidence and resources

Each run has a unique Compose project, `results/<run-id>` and `state/<run-id>`.
Evidence includes configuration, exact runtime/container inspection, raw CSV,
per-minute counts, latency percentiles, telemetry and capture identity
reconciliation. Archives/outboxes are retained after containers stop. No global
Docker prune, shared-volume deletion or PocketHive configuration change is used.
`--keep` leaves the isolated containers running for diagnosis. Fixture credentials
are local benchmark values; only loopback mock/metrics ports are published.
The runner prints capture/heap progress about once a minute. Progress is not a
verdict; successful throughput is computed from the completed CSV files.
Swarm's aggregate service-log export is limited to 30s. A timeout is recorded in
`engine-log-status.json` and cleanup continues; the per-engine CSV, application
and GC logs remain on the result bind mount.

Four engines offer 255/s each for the default aggregate 1,020/s stimulus. They
share an absolute measurement window and use disjoint request IDs. Raw per-engine
CSVs, task states and the merged CSV are retained. Failure or replacement of any
engine fails the run. The Swarm qualifier pins all four engines to this machine;
this does not claim multi-host qualification or extra physical capacity.

Resource caps: mock 4 CPU/4 GiB (3 GiB heap); each of four engines 2 CPU/1.75 GiB
(1 GiB heap); RabbitMQ 2 CPU/1.5 GiB; archive 2 CPU/768 MiB. `swarm.yaml` owns
injector limits; `compose.yaml` owns server/broker/archive limits. Gatling creates
asynchronous users at the offered rate; `--threads` has been removed. Six-second
responses at 1,000/s require about 6,000 in-flight requests across the engines.
Reserve host capacity and disk before a soak. The run aborts at 2 GiB remaining
disk, retaining existing evidence. Each run removes only its own Swarm stack,
Compose services and overlay; the manager remains available for subsequent runs.
For multiple hosts, publish images to a registry and supply explicit placement,
clock synchronisation and result storage/collection; local bind paths alone are
not a portable multi-node deployment.

To run the embedded launcher directly, build with `mvn package`, place the pinned
WireMock standalone3.13.2 jar beside `target/capture.jar`, and run on JDK27:

```sh
CAPTURE_ENABLED=true OUTBOX_PATH=/absolute/outbox.db \
RABBIT_URI=amqp://benchmark:benchmark@localhost:5672/%2f RABBIT_QUEUE=captures \
FIXTURES=/absolute/fixtures \
java --enable-native-access=ALL-UNNAMED -Xmx3g \
  -cp 'target/capture.jar:wiremock-standalone-3.13.2.jar' bench.Headless
```

This native-launch recipe requires your own explicit broker/consumer endpoints;
it does not silently substitute an in-memory sink. Compose is the tested portable
entry point. See [research and prior benchmark context](docs/RESEARCH.md).

## Inspect a capture or repeat the recovery proof

```sh
python3 tools/fault_probe.py --mode official
python3 tools/fault_probe.py --mode headless
python3 tools/read_capture.py --archive state/RUN_ID/archive/events.db --request-id RUN_ID-010000000042
```

The fault probe stops only its own broker, sends 40 exchanges, kills/restarts its
mock, then restarts the broker. It verifies all 120 event identities and full body
bytes after replay. Readback prints full JSON envelopes; bodies use Base64 to
preserve bytes. SQLite files remain inspectable using ordinary SQLite tooling.

## Sequential fixed-delay suite

```sh
python3 tools/qualify.py                 # Plan and storage estimate only
python3 tools/qualify.py --execute       # All 16 hours, one run after another
python3 tools/qualify.py --execute --delay-ms 6000  # Priority: one hour each at 6s
# Explicit smaller batch; resume the same suite to advance through remaining runs:
python3 tools/qualify.py --execute --max-runs 2
python3 tools/qualify.py --execute --resume results/suite-TIMESTAMP --max-runs 2
```

Order: official then headless at 0s, then both at 1s, 1.5s, 2s, 3s, 4s, 5s,
and 6s. Each run mixes 1/5/10/50 KiB and all templates with capture on.
Allow more than 16 wall-clock hours for warmup, capture reconciliation and startup.
The suite rebuilds the injector once to include the current selection protocol.
Full execution needs an estimated **202 GiB free**, including reserve. No evidence
is deleted; smaller batches still accumulate data. To use another filesystem,
copy the repository there, build its images, and execute from that copy.

`results/suite-*/status.json` and `REPORT.md` track progress and link per-run raw
telemetry, JVM/heap/GC evidence, verdicts and durable archives. Failed runs stop
the sequence; `--resume` skips only full-hour passes and retains earlier attempts.
Add `--pause-project NAME --pause-file /absolute/compose.yml` only for an authorized
local stack. It restores exactly the containers it found running on exit.
For an unattended terminal run, use `nohup python3 -u tools/qualify.py --execute
> qualification.log 2>&1 &` (on one shell line). Send SIGINT to the supervisor for
graceful stop. A host shutdown/SIGKILL cannot run restoration; consult the saved
`restoreContainerIds` and restore those containers manually before resuming.

## Resource and overhead reports

Every new completed run writes `results/RUN_ID/REPORT.md` and `summary.json` with:

- Throughput, errors, minute gates, latency and latency minus configured delay.
- Sampled CPU and memory for the mock, RabbitMQ, archive, four engines and total.
- Mock heap min/mean/max, JVM version/flags, raw GC logs and the measurement window.
- Capture completeness and links to retained raw evidence.

Heap is sampled usage, not a heap dump or leak verdict. CPU 100% means one core;
CPU and memory means are arithmetic means of measured-window samples. GC logs
include warmup. Missing samples are marked unavailable.

```sh
# Both commands must use identical settings; change MODE to headless for its pair.
python3 tools/bench.py --mode official --capture off --delay-ms 6000 --size-kib 10 --seconds 120
python3 tools/bench.py --mode official --capture on  --delay-ms 6000 --size-kib 10 --seconds 120
# Substitute the run IDs printed by those commands:
python3 tools/report.py compare --kind capture results/OFF_RUN_ID results/ON_RUN_ID
# Compare official vs headless using the same capture setting and workload:
python3 tools/report.py compare --kind runtime results/OFFICIAL_RUN_ID results/HEADLESS_RUN_ID
# Regenerate summaries from retained evidence (requires selected-cases.json):
python3 tools/report.py summary results/RUN_ID
```

Comparisons write JSON and Markdown in the candidate result directory. They reject
unmatched conditions and failed verdicts. Deltas cover latency, CPU, memory, heap
and throughput; fixed offered throughput is not a maximum-capacity measurement.
Capture-off still loads the extension for metrics, but disables durable capture.
Runtime comparisons include the official image's Java versus OpenJDK27; the
portable headless launcher also runs in a container. Neither comparison isolates
Docker overhead or proves causality from one pair.

The runner has no PocketHive dependency. Stop/restore arguments are optional and
refer only to an explicitly authorized Compose stack. Historical suites created
before explicit size/template selection remain evidence; start a new suite for
those filters rather than changing the meaning of an old run.

## Gatling migration validation

Run Python gates with `python3 -m unittest discover -s tools -p 'test_*.py'`.
The `gatling` Docker build runs the injector Java tests. Run
`python3 tests/perf/verify-failures.py` after building official/Gatling images to
verify corrupt responses, closed connections, actual hashes and absence of POST
replay. A bounded integration:

```sh
RUN_NAMESPACE=build CAPTURE_ENABLED=false docker compose --profile tools build gatling
python3 tools/bench.py --mode official --capture on --target 10 --offered 12 \
  --warmup 10 --seconds 60 --delay-ms 6000 --size-kib 1
```

Repeat with `--mode headless`. For the stop path, add `--continuous`, allow
warmup and a measured interval, then press Ctrl+C once. All four engines drain
and write completion records before CSV reconciliation. Native Gatling logs are
under `engine-N-gatling/`; `engine-N.csv` and `samples.csv` own hash evidence.
Prior reports in `docs/QUALIFICATION.md` describe JMeter runs; the migration does
not relabel those hour-long results as Gatling qualification. Start a new suite;
resuming a saved JMeter suite is rejected.
