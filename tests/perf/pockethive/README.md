# PocketHive WireMock benchmark bundles

This package contains the PocketHive workloads used for the completed official
and headless WireMock comparison, together with preparation, collection and
verification tools. Both runtimes passed the six-second, one-hour measured hold;
see [the endurance report](ENDURANCE-2026-09-30.md) and its recorded limitations.
The [short-run report](RUN-2026-09-29.md) is retained as historical evidence.

## RabbitMQ bundles for new runs

`prepare.py` creates bundles that use **PocketHive's RabbitMQ for Work traffic**.
Fresh official/headless smoke, load and endurance bundles are in
[rabbitmq-20261005/bundles](rabbitmq-20261005/bundles). These bundles have new run
identities and have not been performance-qualified. Their `benchmark.json`
records `workTransport: RABBITMQ`.

| Runtime | Smoke | Load | One-hour hold |
| --- | --- | --- | --- |
| Official | [smoke](rabbitmq-20261005/bundles/ph-wiremock-official-smoke-77287655) | [load](rabbitmq-20261005/bundles/ph-wiremock-official-load-7bb0509e) | [endurance](rabbitmq-20261005/bundles/ph-wiremock-official-endurance-c5a5e6b0) |
| Headless | [smoke](rabbitmq-20261005/bundles/ph-wiremock-headless-smoke-1f84bda5) | [load](rabbitmq-20261005/bundles/ph-wiremock-headless-load-be6daac2) | [endurance](rabbitmq-20261005/bundles/ph-wiremock-headless-endurance-6fdd726e) |

The Work adapter settings match the earlier
[RabbitMQ comparison](hfm-rabbit-20261001/README.md): prefetch 50, one consumer,
nonexclusive consumption, persistent output and publisher confirms disabled.
All 13 Work input/output boundaries select RabbitMQ explicitly. Broker connection
settings come from the selected PocketHive deployment; no separate Work broker
or broker credentials are embedded in these bundles. The evidence worker still
writes compact results to Redis.

Fresh `scenario.yaml` and `sut.yaml` files use conventional YAML formatting;
`benchmark.json` remains JSON. Historical snapshots retain their original format.
Selection is explicit: these bundles do not inherit or switch to Artemis. A local
probe against PocketHive 0.15.35 libraries accepts all 54 workers with RabbitMQ
bootstrap and rejects all 54 with Artemis bootstrap during resolved configuration
validation, because their Rabbit destinations remain unresolved. This checks the
configuration path, not a live deployment or performance run.

## Historical Artemis bundles

| Runtime | Smoke: 4/s, 12s | Load: 1,020/s, 90s | Endurance: 1,020/s, 3,690s |
| --- | --- | --- | --- |
| Official | [smoke](bundles/ph-wiremock-official-smoke-bd3d6349) | [load](bundles/ph-wiremock-official-load-b3a7a205) | [one-hour hold](bundles/ph-wiremock-official-endurance-eaa015f7) |
| Headless | [smoke](bundles/ph-wiremock-headless-smoke-fbf2f085) | [load](bundles/ph-wiremock-headless-load-87275207) | [one-hour hold](bundles/ph-wiremock-headless-endurance-8a9ee9f1) |

Each directory includes `scenario.yaml`, `benchmark.json`, finite CSV datasets
and a `sut/<runtime>/sut.yaml` target. These are exact historical bundle snapshots,
including their original IDs and endpoints. Generate a fresh bundle for another
run; replaying completed IDs can invalidate capture deduplication and evidence.

The endurance profile has four lanes at 255/s, 60 seconds warmup, a 3,600-second
measurement window, and 30 further seconds of arrivals before draining. It offers
3,763,800 requests per runtime. Each lane reads 940,950 rows from a shared CSV and
adds its own lane prefix to create unique 29-character IDs. All profiles cycle
1/5/10/50 KiB bodies and static/JSON/text responses with a fixed 6,000ms delay.
The pass target is 1,000/s; the offered rate explicitly includes 2% headroom.

New `diagnostic` bundles use 60 seconds warmup, 180 measured seconds and 30 seconds
of final arrivals at the same 1,020/s rate. Fresh bundles also record the existing
PocketHive observability hops (service, receivedAt, processedAt) and processor
pacing milliseconds. No PocketHive service change is needed. Processor hop end
is measured after the response body and result construction, before output
publication; it is not a timestamp taken exactly at the socket's final byte.
The evidence timestamp remains evidence-stage time, not HTTP completion time.
Use the processor hop to distinguish request-queue waiting, processor work and
downstream evidence delay. Reject missing/ambiguous processor hops rather than
substituting evidence time. Cross-host stage differences require synchronized
clocks; the current injector's workers share one workstation clock.

Run `stage_timing.py --bundle BUNDLE --results RESULTS.jsonl --output NEW_REPORT.json`
on these fresh records. This diagnostic supports gzip input and reports processor
completion and evidence rates separately; body/archive checks still belong to
`analyze.py` / `stream_verify.py`. The prepared HFM sequence and required capture
flags are in `hfm-throughput-20260930/run-plan.json`. Verify the selected server's
live `wiremock_capture_enabled` value before starting each run. Capture-off runs
are baseline diagnostics, never lossless-capture qualification.

The local storage/HTTP validation for the pending HFM fix is recorded in
`hfm-throughput-20260930/validation.json`. To reproduce the storage-only probe,
run `mvn package`, compile `tests/perf/OutboxThroughputProbe.java` against
`target/capture.jar`, then run `bench.OutboxThroughputProbe NEW_DB_PATH 32 2000`.
Use a fresh database for each probe. `TimingTemplateProbe.java` compiles against
the deployed PocketHive 0.15.35 worker libraries and takes the generated evidence
template file as its argument; it checks the actual Pebble/WorkItem/hop contract.

## Required environment

For new bundles, configure the selected PocketHive deployment with
`POCKETHIVE_WORK_TYPE=RABBITMQ` before creating the swarm. In HiveForge, set this
runtime value for PocketHive's existing profile and update that deployment.
PocketHive supplies the workers' RabbitMQ connection settings. The generator and
processor lanes exchange Work through that broker; the evidence worker consumes
their RabbitMQ results and writes to the dedicated Redis evidence sink.

WireMock's independent durable capture goes through its configured RabbitMQ
connection into the archive. The RabbitMQ in the standalone Portainer WireMock
lab does not replace PocketHive's Work broker or Redis. No postprocessor
reconciliation adapter is included. The original September 30 environment used
PocketHive 0.15.35 with Artemis; its historical snapshots retain that transport.

Provision a compatible PocketHive deployment with the generator, processor,
moderator and swarm-controller images corresponding to the tested release. The
bundle image names use PocketHive's original `:latest` declarations; resolve them
through the selected deployment's supported image configuration and record the
actual image digests for a new run. Copying these bundles does not establish
compatibility with a different PocketHive release or transport.

Provision the [portable WireMock lab](../../../docs/PORTAINER.md) separately, or
use equivalent canonical fixtures/resource limits. Redis must be reachable from
the workers, persistent, dedicated to benchmark evidence and configured without
eviction. The collector uses plain Redis without authentication/TLS; use an
isolated endpoint matching that explicit adapter configuration. Redis is not
included in the generator-independent Portainer lab.

Run one WireMock target at a time. The original processors each permit 1,800
outstanding requests and use `PER_THREAD` HTTP connections. Approximately 6,120
requests are in flight at the endurance rate and six-second delay. The measured
PocketHive workers/controller consumed about 9 GiB and 2.9 CPU cores, excluding
shared infrastructure. Allow capacity and evidence storage before a hold.

## Prepare a fresh run

Run from the `wiremock-benchmark` repository root, using Python 3.10+:

```sh
python3 -m pip install -r tests/perf/pockethive/requirements.txt
python3 tests/perf/pockethive/prepare.py \
  --canonical-repo . --output results/pockethive-official \
  --runtime official --mode endurance
```

Use `--runtime headless` for the other target, or `--mode smoke` / `--mode load`
for the shorter profiles. Preparation generates the canonical fixture catalogue
from this repository's `tools/fixtures.py`, fresh request/run IDs and a bundle
under `<output>/bundles/<scenario-id>`. It does not deploy or start any load.

Before importing the generated bundle, explicitly configure its endpoints:

1. Set `endpoints.default.baseUrl` in `sut/<runtime>/sut.yaml` to the WireMock URL
   reachable by PocketHive workers, for example `http://SWARM_HOST:19080` for
   official or `http://SWARM_HOST:19081` for headless. The historical defaults
   `wmb-ph-official:8080` and `wmb-ph-headless:8080` only work on the original network.
2. In `scenario.yaml`, find the bee with role `evidence` and set
   `config.outputs.redis.host` and `port` to the dedicated result sink. The
   original default is `wmb-ph-results:6379`. Keep the run-specific `defaultList`
   unchanged, and use the same Redis endpoint when collecting.
3. Validate and publish through the selected PocketHive environment's supported
   bundle import/MCP workflow. For Git-backed publication, commit the fresh bundle
   and supply its exact repository path and commit. Keep credentials and raw
   results outside Git. Select the bundle's matching SUT when creating the swarm.

Do not change shared PocketHive WireMock mappings or broker settings. Do not
attach a postprocessor as a competing consumer of the capture archive queue.

## Collect and verify

Start the collector before enabling the finite swarm. Read `runId` and
`expectedRequests` from that generated bundle's `benchmark.json`:

```sh
python3 tests/perf/pockethive/collect.py \
  --run-id RUN_ID --host REDIS_HOST --port 6379 \
  --expected-count 3763800 --max-seconds 4500 \
  --output results/pockethive-official/results.jsonl.gz
```

For smoke/load profiles, use the manifest's request count and write plain
`results.jsonl` for the short-profile analyzer. The collector destructively drains
only the selected run's Redis list into the result file, rejecting duplicate or
unexpected IDs. Require a complete count and an empty final list. After all HTTP
responses and captures drain, save the target's JSON capture metrics and a
consistent `events.db` archive copy before verification.

For endurance, use the included frozen bounded-memory verifier and a new scratch
database path on a disk with enough space:

```sh
python3 tests/perf/pockethive/stream_verify.py \
  --bundle results/pockethive-official/bundles/SCENARIO_ID \
  --results results/pockethive-official/results.jsonl.gz \
  --archive /PATH/TO/events.db --metrics /PATH/TO/final-metrics.json \
  --canonical-repo . --database /PATH/TO/new-verifier.sqlite \
  --output results/pockethive-official/verdict.json
```

Use `analyze.py` for smoke/load profiles with the same arguments except
`--database`, and an uncompressed results file. It reads the short profile's
`benchId` columns and is not compatible with the endurance `sequence` format.
A failed integrity/rate verdict exits 2. `test_analyze.py` runs five negative
checks against a supplied passing short-run evidence set.

Measure offered rate, server completions, result integrity and resources
separately. Processor HTTP timing ends at response headers; PocketHive pipeline
latency includes queues and evidence processing. Neither is equivalent to full
client-observed response latency. Grafana counters alone are not reconciliation.
The verifier's archive checks are described by its implementation and historical
report; preserve raw captures for independent body-level investigation.

## Provenance and validation

[source-provenance.json](source-provenance.json) records the PocketHive source
repository, commits and SHA-256 hashes at the original import. The six historical
bundle snapshots and reports retain their original transport and identities.
`prepare.py` now generates RabbitMQ bundles and `WorkConfigProbe.java` reads YAML;
the original provenance does not describe those updated tools or the new bundles.
Fresh bundle hashes are recorded in
[preparation.json](rabbitmq-20261005/preparation.json). `stream_verify.py` is
copied from the retained endurance artifact volume and matches the hash recorded
in [the original provenance](evidence-endurance-2026-09-30/provenance.json).
The other run-specific monitor/resource scripts remain in that artifact volume;
this package does not claim to include the large raw result/capture databases.

The historical results apply to their recorded images and environment, not a
fresh endurance qualification of the newer instrumented Portainer images.
`TemplateProbe.java` and `WorkConfigProbe.java` are retained release-specific
checks requiring PocketHive's Java dependencies, not standalone benchmark builds.
`RabbitWorkTransportProbe.java` additionally checks correct RabbitMQ bootstrap
and wrong-Artemis rejection for the fresh RabbitMQ scenarios without connecting
to a broker. Compile these configuration probes against PocketHive's release
libraries and pass the generated `scenario.yaml` paths as arguments.
