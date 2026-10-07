# Benchmark contract

Goal: demonstrate WireMock 3.13.2 at 100–1,000 successful requests/s with 0–6s
intentional delay, full external request/response capture, and a one-hour hold.
Results are measurements on declared hardware, not a guarantee on every host.

## Workloads and comparisons

Sizes are exact UTF-8 **KiB (1024 bytes)**; the matrix uses equal 1/5/10/50 KiB bodies. Templates are
static JSON, dynamic JSON correlation and dynamic text correlation. Delays are
0/1000/1500/2000/3000/4000/5000/6000ms. Padding is deterministic and compressible;
HTTP compression is disabled. Archive compression does not reduce network load.

One generated case catalogue owns fixtures and client expectations. Both modes
use identical WireMock tuning, fixtures and the exact same extension jar:
- official `wiremock/wiremock:3.13.2`, retaining its supplied Java runtime;
- embedded WireMockServer on OpenJDK 27 GA (headless, also runnable outside Docker).
The second mode is containerised for portability; this is not a pure isolation of
container overhead. Record JVM, image digests, host, quotas and extension state.
Hooks-off baselines and hooks-on runs are separate named experiments. MockServer
is optional later work, not a substitute for the primary WireMock deliverable.

## Durable capture

The extension writes REQUEST before matching in BENCHMARK_HEADERS mode and after
matching in STUB_JSON mode, RESPONSE_PREPARED before send, and SEND_COMPLETED after
WireMock's completion callback. Payloads contain run/request
IDs, phase, timestamp, method/URL, headers and complete body bytes. Completion
means server callback observed, **not proof the client received the response**.
Headers are the WireMock lifecycle view, before any transport headers added by
the HTTP container; this is application capture, not a raw packet recording.
With asynchronous delay, WireMock 3.13.2 can invoke the completion callback before
the delayed socket write. Even a completion event does not establish delivery;
only the client can verify it. Requests not yet durably accepted at hook entry cannot
be promised to survive a process/OS failure. No replay of HTTP requests occurs.

The full JSON capture envelope is zlib-compressed (level 1) before disk commit
and is published with `content_type=application/json`, `content_encoding=deflate`.
The consumer stores those exact compressed envelope bytes. Decoding is bounded
to a 1 MiB JSON envelope, well above the declared 50 KiB body workloads. This
reduces capture IO for the explicitly compressible fixtures; HTTP remains
uncompressed and all decoded body bytes are retained.

SQLite WAL with synchronous=FULL is the disk outbox. A single writer batches
commits; the callback waits for its own durable commit. This unavoidable disk cost
is measured. RabbitMQ IO occurs on a separate publisher thread. Persistent
messages, durable queue, mandatory routing and publisher confirms precede outbox
deletion. Recovery can duplicate a publish, so event IDs are stable and archive
insertion is idempotent. No memory-only success and no silent drop policy.
Broker outage retains committed records and reconnects to that same configured
broker. Outbox/disk exhaustion fails the benchmark, never silently discards data.
In-memory batching is bounded. Process termination on capture storage failure
prevents continuing to claim a healthy lossless capture service.

The outbox has one transaction writer for both appends and confirmed deletions.
Both operations enter the same bounded FIFO; successful futures are completed
only after the FULL/WAL transaction commits. The publisher reuses one read
connection. Pending-event telemetry is initialized from persisted rows and
updated only after commits; scrapes do not open SQLite connections or count the
table. Shutdown rejects new operations, drains accepted operations, then closes
the read connection. Duplicate append IDs fail the writer and all waiting callers.

Capture diagnostics expose queue depth, append wait count/seconds/max, transaction
count/seconds/max, maximum committed append batch size, and completed publisher
cycle stage seconds (read, publish/confirm, delete). Durations use a monotonic clock. These measurements
do not prove archive reconciliation or HTTP client delivery. JSON/Prometheus
metrics are projections of the same counters, with zero values when capture is off.

An independent RabbitMQ consumer durably archives the complete compressed event
before acknowledging delivery. This both proves external receipt and bounds
broker queue growth for soak. Archive size/disk headroom are monitored. Consuming
is explicit test processing, not an assertion RabbitMQ retains acknowledged data.
The archive remains a portable SQLite file containing full replayable events.

## Direct RabbitMQ capture (filesystem-free mocks)

### Capture identity and live stub configuration (envelope version 2)

`CAPTURE_IDENTITY_MODE` is required when capture is enabled and explicitly selects
`BENCHMARK_HEADERS` or `STUB_JSON`. The first preserves the existing `/bench/`
selection and mandatory benchmark headers. `STUB_JSON` requires no client headers
and selects matched stubs containing `response.transformerParameters.capture`,
on any non-admin request path. Stubs without that block and unmatched requests are
not captured in this mode. The block requires exactly these fields:

```json
{"runId":"work-test-001","correlationJsonPath":"$.correlationId","missingCorrelation":"RECORD_UNCORRELATED"}
```

The run ID is a nonblank string of at most 256 characters. JSONPath must select a
single value (no wildcard/filter/multiple-result paths). Supported correlation
values are nonblank strings up to 256 characters. Missing/null/blank values are
`MISSING`; malformed JSON is `INVALID_BODY`; non-string/oversized values are
`INVALID_VALUE`. In these cases `correlationId` is empty and full capture continues.
The sole supported missing-value policy is the explicit `RECORD_UNCORRELATED`.
Invalid capture configuration is rejected on stub creation/edit before replacing
the active mapping. A valid live edit applies to subsequent matches; each request
snapshots its matched configuration and correlation once, before response rendering.

Version 2 adds required `schemaVersion: 2`, `correlationId` and
`correlationStatus` (`PRESENT`, `MISSING`, `INVALID_BODY`, `INVALID_VALUE`) to the
capture envelope. In `STUB_JSON`, `requestId` is WireMock's generated serve-event
UUID and identifies one exchange, even if business correlation values are missing
or duplicated. `runId`, `requestId`, `correlationId` and `correlationStatus` are
identical across its three phases. `BENCHMARK_HEADERS` keeps the header-derived
request ID and also records it as `correlationId` with status `PRESENT`.

STUB_JSON captures REQUEST after matching and before response templating; it
cannot promise capture for a request that fails before matching. The existing
header mode captures REQUEST before matching. Both capture the rendered response,
including an empty HTTP 200 (`bodyBase64: ""`), without modifying its body or
headers. STUB_JSON rejects request bodies over 64 KiB with 413 before matching,
even on unselected stub paths; it does not validate application JSON schemas.
Admin endpoints are not subject to the stub request filter.

The archive preserves the version-2 envelope in `payload_zlib` and groups/indexes
by internal request ID; business correlation is read from the stored envelope.
Consumers must explicitly support version 2. Version-1 envelopes are rejected by
the new decoder: use fresh queues/archives and deploy mock and archive images from
the same build. Old images remain unchanged; no silent schema compatibility is
introduced. Missing business IDs still prevent definitive per-client reconciliation.

Live mappings use WireMock's ordinary POST/PUT `/__admin/mappings` API. Read-only
images do not persist those edits across replacement; retain and reapply the
mapping externally. Response templates may optionally reference
`parameters.capture.correlationJsonPath`; response templating and a response body
are not prerequisites for capture correlation. See `docs/DYNAMIC-CAPTURE.md`.

The dedicated-broker Portainer variations add a persistent single-node RabbitMQ
and the existing commit-before-ack archive consumer. They retain this direct
capture contract. Broker boot imports a ready-message count/byte limit with
`reject-publish`, not record eviction; rejection fails capture and the run.
Broker and archive directories require explicitly selected node-local storage.
Queue bounds are not total disk bounds and archive retention remains operator
owned. See `deploy/portainer/DIRECT-WITH-RABBIT.md` for the deployment contract.

The four generated `stack-direct-*.yml` Portainer files pin the published version-2
mock images directly; the dedicated-broker files also pin their matching archive.
`deploy/portainer/direct/dynamic-image-lock.json` owns those image references.
`OFFICIAL_DIRECT_IMAGE`, `HEADLESS_DIRECT_IMAGE` and `ARCHIVE_IMAGE` are not
deployment selectors in these files. The direct example environments select
`STUB_JSON`; existing benchmark bundles must explicitly select `BENCHMARK_HEADERS`.
Local verification harnesses may explicitly substitute a matched unpublished
build for testing; that does not change the deployment pins.

`CAPTURE_MODE` explicitly selects `OUTBOX` (the SQLite contract above) or
`DIRECT_RABBIT` when capture is enabled. Container images for the original path
set `OUTBOX`; the two direct Portainer deployments set `DIRECT_RABBIT`. There is
no automatic switch between modes. Capture disabled opens neither sink.

Direct capture preserves the same three phases, IDs, complete bodies and zlib
encoding. It requires `RABBIT_URI`, `RABBIT_QUEUE`, `RABBIT_QUEUE_TYPE` (`classic`
or `quorum`) and `CAPTURE_CONFIRM_TIMEOUT_MS` (positive milliseconds). The queue
is durable, non-exclusive and not auto-deleted, and its declared type must match
an existing queue. Use dedicated capture queues, never PocketHive work queues.
No TTL, overflow/drop policy or premature consumer acknowledgement is compatible
with retained evidence; the broker/consumer operator owns those policies.

A single publisher batches up to 256 events with at most 2 ms collection time.
At most 1,024 operations may be admitted, including the batch awaiting confirmation.
Each callback waits for mandatory, persistent publication and a positive broker
confirmation; a return, nack, connection failure, deadline or full admission
window fails explicitly. No retry/replay from memory is claimed. A confirm lost
on the network leaves delivery uncertain; consumers must deduplicate event IDs.
Unconfirmed process memory is not durable. Startup requires a usable broker.
Shutdown rejects new work and fails unconfirmed operations. Capture failure stops
the mock with exit 70 rather than continuing a misleading successful run.

Client validation is not a capture-storage failure. With capture enabled in BENCHMARK_HEADERS mode,
`/bench/` requests require exactly one nonblank `X-Bench-Run` and `X-Bench-Id`,
each at most 256 characters. Invalid correlation returns HTTP 400. Request bodies
over 64 KiB return HTTP 413 (the workload maximum remains 50 KiB). Rejection occurs
before capture/matching and does not terminate the process. Rejected requests do
not produce correlated captures or enter the valid-request lifecycle counters;
`rejectedRequests` / `wiremock_capture_rejected_requests_total` count them separately.
Non-benchmark/admin paths retain normal WireMock handling. Configured fixtures
retain their existing matching behavior; this is not a general JSON schema validator.

Unlike OUTBOX, broker outages cannot be buffered locally. The confirmation
wait is part of request processing and must be measured. `pending` means admitted
but unconfirmed memory operations; `committed` and `confirmed` both count positively
confirmed events in DIRECT_RABBIT. JSON metrics include `mode`; direct diagnostics
include callback wait and publish/confirm durations and do not pretend to measure
SQLite transactions. Broker connection telemetry also checks the live connection.

The external-broker direct stacks contain one mock each and reuse an explicitly addressed
PocketHive RabbitMQ. Images contain immutable fixtures, GC/application logs go to
stdout, the root filesystem is read-only and `/tmp` is bounded tmpfs scratch.
There are no persistent volumes, EFS mounts, archive services or bundled broker.
RabbitMQ and the downstream consumer still own durable storage. A confirmed
publish is not a reconciliation verdict. Consumers must decode the capture
contract and acknowledge only after their required durable processing succeeds.
These files do not configure a PocketHive postprocessor or prove its compatibility.

The existing SQLite archive/recovery runner remains the OUTBOX qualification
path. Direct capture needs its own client/body/ID reconciliation and fault proofs;
previous hour results do not qualify these images. Existing server callback
completion/in-flight metrics are not actual client delivery counters with async
responses; use client results for throughput and latency verdicts.

The direct Swarm stacks restart on operational failure after 5 seconds, with no
finite retry ceiling. Each restart repeats strict broker startup checks. This is
service recovery, not request/capture replay: a restart or capture failure still
fails the benchmark run. Incorrect configuration must be corrected explicitly.

## Listener backlog

`WIREMOCK_ACCEPT_BACKLOG` is a required positive integer (1–2147483647) for
both runtimes. Set `WIREMOCK_ACCEPT_BACKLOG=4096` for the next startup comparison.
The official runtime receives `--jetty-accept-queue-size`; headless passes the
same value to `jettyAcceptQueueSize`. Missing settings fail explicitly.
This is the pending connection accept queue, not the number of active requests
or Jetty request threads. Linux caps the effective backlog at the container's
`net.core.somaxconn`; this change does not modify that kernel setting.
Changing the backlog requires recreating the mock. Stop and drain load/capture
first, and record the value with the run. A larger backlog is a startup mitigation
to test, not a throughput qualification or a fix for PocketHive failure records.

## Verdict

Warmup (60s by default), measured hold and final response/capture drain are distinct.
Gatling uses native constant open arrivals from the common launch barrier. Pass requires:
- all started measured HTTP requests finish successfully with exact payload size,
  template content/correlation and at least the configured delay;
- injector arrivals stay within 5% of the configured offered rate overall and
  per full measured minute (for runs of at least a minute); startup catch-up
  cannot masquerade as the configured stimulus;
- delivered throughput reaches the declared target overall and in every full
  measured minute; no generator shortfall may be called a WireMock pass;
- REQUEST/RESPONSE_PREPARED/SEND_COMPLETED unique archive IDs reconcile with each
  completed client request; pending outbox is drained, no capture error or lost ID;
- no OOM/restart and no sustained unbounded queue growth. Record memory/CPU/disk,
  capture lag, per-minute throughput and delay-adjusted p50/p95/p99/max latency.

The offered rate and pass target are separate, visible inputs. Qualification may
explicitly offer 1,020/s to establish at least 1,000/s in every minute despite
scheduler jitter; it must report the actual 1,020/s stimulus. A finite test cannot
prove indefinite stability. A one-hour pass proves that run; continuous mode
keeps the same processes running until explicitly stopped (one-year scheduler ceiling),
then drains and reports the actual observed interval.

Broker outage/recovery and process-kill/outbox replay are separate functional
proofs; a failed fault run never becomes a normal throughput pass. Disk cannot
buffer an unlimited outage; capacity is part of the recorded envelope.

Gatling 3.15.1 on Java 21 owns scheduling through `constantUsersPerSec`:
one virtual user performs one request; all users share reusable HTTP connections.
There is no thread-per-client budget and `--threads` is removed. At 1,000/s and
six-second responses, about 6,000 requests must be in flight across the four
engines. Container and heap limits remain explicit in `swarm.yaml`.
No scenario retry loop is used. Bodies use Gatling’s consumable input-stream
transport so a consumed POST cannot be replayed after a pooled connection closes.
Redirects, caching and HTTP compression are disabled. Requests time out after 30s. Each request verifies status 200, exact body bytes/correlation and
elapsed time plus 2ms at least the declared delay.

Each engine starts its JVM before the absolute launch barrier; missing that
barrier fails the engine. New requests stop at the absolute hold end or when
`stop.requested` appears in the run directory. A control scenario waits for all
admitted requests to finish before calling Gatling's `stopLoadGenerator`.
The one-year injection ceiling also applies to continuous mode. No process restart
or repeated short runs implement continuous mode.

`engine-N.csv` is the client evidence contract (UTF-8, comma-separated header):
`timeStamp,elapsed,success,bench_id,case_id,delay_ms,payload_bytes,request_sha256,response_sha256`.
Times are request start epoch milliseconds and client-observed elapsed milliseconds;
`success` is lowercase `true`/`false`. Hashes describe actual transmitted request
and completed response bytes, including invalid HTTP responses, never the expected
body. A transport failure without a complete response records `success=false` and
the empty-body hash; partial transport bytes are not exposed by Gatling checks.
Each admitted request produces exactly one row, including transport failures.
`engine-N-completion.json` records admitted/completed counts after the CSV closes.
All four nonempty CSVs must match those counters before merging into `samples.csv`.
A missing completion record or unfinished request fails the run. Native Gatling
binary logs and engine application/GC logs are retained alongside this projection.
Old JMeter evidence remains historical; it is not Gatling qualification.

## Four-engine Docker Swarm execution

The user requested four Docker Swarm engines. Run four independent Gatling CLI
processes against one mock; each receives one quarter of the aggregate offered
rate (255/s for 1,020/s total). They share an absolute measurement window and use
engine-specific request IDs. Rates are combined;
the target is 1,000/s total, not 1,000/s per engine. Keep every engine's CSV and
merge all four streams for the same identity/body reconciliation gate.

The local qualifier pins tasks to this manager node with prebuilt local images
and a run-specific attachable overlay. Images include the compiled simulation;
the selected catalogue is read from the run directory. Each task has 2 CPU,
1.75 GiB RAM and a 1 GiB heap; no task restart is
allowed. A missing/failed/replaced engine fails the run. The injector resource
owner is `swarm.yaml`; mock/broker/archive limits remain in `compose.yaml`.
This is four engines on one host, not a multi-host qualification. Multi-host use
requires distributable images, reachable mock endpoints, synchronised clocks,
and result storage/collection on each node.

## Fixed-delay qualification suite

`tools/qualify.py` schedules official then headless at each catalogue delay:
0, 1, 1.5, 2, 3, 4, 5 and 6 seconds. Each of the 16 runs has 60 seconds
warmup and 3,600 measured seconds, capture on, four engines, target 1,000/s,
and explicit offered rate 1,020/s. Each delay mixes all four body sizes and
all three templates (dynamic JSON, dynamic text and a static control).
`bench.py --delay-ms` selects one delay; it cannot combine with an exact `--case`.
The runner writes the selected catalogue into each result directory; engines
read that same selection rather than implementing their own selection policy.

`qualify.py --delay-ms 6000` explicitly limits the suite to both runtimes at 6s.
`--max-runs` limits a batch without changing the saved schedule.
The suite records the pinned generator identity and stops on the first failure.
Resume rejects suites from another generator (including pre-migration suites),
and skips only matching-generator, successful full-duration verdicts.
Failed/interrupted attempts and all capture data remain.
A plan alone is not a qualification. Raw CPU/container memory time series,
sampled mock heap, JVM metadata, mock/engine GC logs, CSV, captures and verdicts
are retained per run. Suite JSON and Markdown link these artifacts and summarize
throughput, errors and sampled heap. Heap samples do not constitute a heap dump
or proof of absence of memory leaks.

Before executing, require 12 GiB per remaining run plus 10 GiB reserve, based on
the observed 11.6 GiB/hour footprint; this estimate is not a storage guarantee.
Repeat the check between runs and keep the existing 2 GiB live-run abort gate.
Never delete previous evidence automatically. Run the repository on a filesystem
with enough space. Building engines and starting a suite require no other
benchmark stack to be active. Optional explicit Compose project/file arguments
pause only that stack's currently running containers and restore those same
containers on normal exit, failure, SIGINT or SIGTERM. Restoration errors fail
the suite. SIGKILL/host power loss cannot execute cleanup; restoration evidence
and container IDs are retained for manual recovery.

## Portable workload selection and resource reports

The supported runner environment is Python 3.10+ on a Linux Docker host (including
Windows through WSL2). macOS Docker Desktop can use the same recipes and shared
bind paths but is not qualified here; native Windows Python is unsupported by the
POSIX suite lock. No PocketHive installation or user-specific paths are required.

`bench.py --size-kib 10` fixes both request and response at 10 KiB;
`--size-kib 1 50` cycles that subset. Omission selects all catalogue sizes.
`--template json text` selects dynamic templates; omission also includes the static
control. These filters compose with `--delay-ms` (one of 0/1000/1500/2000/3000/4000/
5000/6000), or omitted delay cycles the full range. Exact `--case` is mutually
exclusive with all workload filters. Selection is shared by
client assertions and the persisted per-run catalogue. `qualify.py` accepts the
same size/template filters and saves them for all runs and resume.

Each completed run writes `summary.json` and `REPORT.md`: measured-window sampled
mock heap min/mean/max; JVM version and declared JVM flags; per-container sampled
CPU percent and memory bytes; latency including and excluding intentional delay;
throughput, errors, capture verdict and links to raw JVM/GC/telemetry evidence.
CPU 100% represents one CPU core; sample means are arithmetic, not time-weighted.
Missing metrics remain explicitly unavailable, never zero. Sampled heap peaks are
not allocation totals, retained heap, or proof of leak freedom. GC files cover the
whole process including warmup and remain available for inspection.

`tools/report.py compare --kind capture BASELINE CANDIDATE` compares capture off
then on for the same runtime. `--kind runtime` compares official then headless
at the same capture setting. Reject comparisons with differing selected cases,
measurement duration, rates, warmup, injector version/arrival model/count, host, source workload,
container quotas/JVM flags, or injector image. Capture comparisons additionally
require the same mock image and JVM. Both verdicts must pass. Runtime comparisons
explicitly include different JVM implementations/versions and are not a pure
Docker-overhead experiment. Reports show absolute deltas and percentage changes
(where the baseline is nonzero) for throughput, delay-adjusted latency, sampled
heap and mock/whole-stack CPU and memory. A fixed offered rate cannot measure
maximum capacity; these are observed paired differences, not causal guarantees.
