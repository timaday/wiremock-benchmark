# WireMock with direct PocketHive RabbitMQ capture

For an isolated broker plus a compatible archive consumer, use the
[dedicated RabbitMQ variation](DIRECT-WITH-RABBIT.md). It keeps the mock
filesystem-free while storing broker data and capture archives on explicit
node-local paths.

The [dynamic capture guide](../../docs/DYNAMIC-CAPTURE.md) covers the new
version-2 build, `CAPTURE_IDENTITY_MODE=STUB_JSON`, per-stub correlation and empty
responses. The published direct-2 images documented below retain version 1 and
header admission; they do not acquire dynamic behavior from an environment change.

Upload **`stack-direct-headless.yml`** or **`stack-direct-official.yml`** as a named
Portainer Docker Swarm stack. Each file contains just one mock. Both retain full
capture and the same fixtures/tuning; neither needs a writable persistent volume,
EFS, its own RabbitMQ, SQLite archive, Prometheus or Grafana.

The root filesystem is read-only. A 64 MiB RAM-backed `/tmp` supports JVM scratch
files; logs go to stdout. Fixtures are baked into the image. Runtime mapping
changes that require filesystem writes are intentionally unsupported.

## Published images and future builds

Both `20261005-direct-2` images are now published publicly to GHCR.
`example-direct.env` pins their verified digests from [direct/image-lock.json](direct/image-lock.json);
Portainer can pull them without registry credentials. No local build is needed
to deploy this release.

The older outbox tags cannot implement direct capture. To build a future version,
choose a fresh tag and run:

```sh
python3 deploy/portainer/direct/build.py \
  --prefix ghcr.io/timaday/wiremock-lab --tag 20261005-direct-3
```

This requires Java 21, Maven, Python 3 and Docker on the build machine. It runs
tests and resolves both base images from `image-lock.json`; fixtures and the
official/headless JVM versions stay matched to those bases. The locked images
are Linux AMD64. It builds locally and records image IDs under `target/direct-image`.
The script does not publish. To publish a future build, use its fresh tag:

```sh
docker push ghcr.io/timaday/wiremock-lab-official:20261005-direct-3
docker push ghcr.io/timaday/wiremock-lab-headless:20261005-direct-3
```

Use a new tag for subsequent builds and preferably put the resulting digest
references into Portainer's image variables. GHCR package visibility/registry
credentials must allow every eligible Swarm node to pull the new packages.

## Portainer settings

Load `example-direct.env`, replacing its placeholder values. Select an eligible
worker with 4 CPUs and 16 GiB RAM through `LAB_NODE`. The mock retains the existing
4 CPU / 4 GiB limit and 3 GiB heap; fewer services is the primary resource saving.
Run one mock at a time on that worker for a comparison, or use separate workers.

`POCKETHIVE_NETWORK` must name an existing Swarm overlay network on the **same
Swarm**. This attaches the mock to the broker's network; no host path is needed.
`POCKETHIVE_RABBIT_URI` must be reachable from that network and select the correct
vhost. Percent-encode credentials/vhost as appropriate. Do not paste real
credentials into Git. Connection secrets remain normal environment settings,
as requested for this lab; Docker secrets are not required.

`CAPTURE_PREFIX` produces separate queues `<prefix>.headless` and
`<prefix>.official`. Use fresh queues for this experiment. `RABBIT_QUEUE_TYPE`
explicitly chooses `classic` or `quorum`; it must match an existing queue. These
are **capture queues**, not PocketHive processor work queues. A broker queue type
mismatch fails startup instead of changing configuration. Check for broker policies
that expire/drop messages. A queue without an active consumer grows continuously.

With the example environment, point the existing benchmark bundles/generator at
`http://<swarm-host>:19281` (headless) or `:19280` (official). The files' built-in
port defaults remain 19081/19080 if the example overrides are omitted. Send the
same `/bench/...` workloads and required `X-Bench-Run` / `X-Bench-Id` headers.
The image healthcheck uses `/__admin/health`, not an uncorrelated benchmark request.

Bad benchmark requests do not kill the mock: missing, blank, duplicated or overlong
correlation headers return **400**, and request bodies over **64 KiB** return **413**.
The maximum fixture remains 50 KiB. Rejections are counted separately as
`wiremock_capture_rejected_requests_total` / JSON `rejectedRequests`; they have no
correlated capture events. The next valid request continues in the same process.

Backlog remains explicitly set to 4096; Linux's effective `somaxconn` cap still
applies. Async responses use 64 threads with 128 container threads. Six-second
delay fixtures and all body sizes/templates are unchanged.

Existing monitoring on the same overlay can scrape port 8081 `/prometheus` using
the full Swarm service name (`<stack>_headless` or `<stack>_official`). JSON state
is at `/metrics`. `mode` must say `DIRECT_RABBIT`, `brokerConnected` must be true,
and capture errors must be zero before load. `pending` counts memory operations
awaiting broker confirmation. In this mode `committed` equals `confirmed`; neither
means the downstream consumer completed reconciliation. Existing HTTP completion
and in-flight metrics reflect WireMock callbacks, which can precede async delivery;
use generator results for actual completed throughput and elapsed latency.

## Consumer and failure contract

The capture envelope/encoding is unchanged: persistent AMQP messages with
`content_type=application/json`, `content_encoding=deflate`, and `message_id=eventId`.
Inflate the envelope, preserve IDs/phase and Base64-decode `bodyBase64`. Full
request/response bodies are retained. A request normally creates REQUEST,
RESPONSE_PREPARED and SEND_COMPLETED. The last phase records WireMock's callback,
not proof of client delivery.

The PocketHive consumer must explicitly support this envelope and acknowledge
only after its required durable processing succeeds. This deployment does not
install or assert a compatible postprocessor. Reconcile identities and body hashes
against client results before declaring a benchmark pass. RabbitMQ still needs
suitable durable storage; these files do not change its existing storage setup.

Every callback waits for mandatory publication and publisher confirms. Batches
amortize broker round trips. The admission window includes at most 1,024 unconfirmed
events. `CAPTURE_CONFIRM_TIMEOUT_MS=10000` bounds each callback's wait. Startup
fails without RabbitMQ; during a run, connection loss, negative/unroutable publish,
timeout or full admission window fails capture and stops the process (exit 70).
Swarm restarts a failed mock after 5 seconds and keeps trying startup until the
broker/configuration is usable again. A service recovery does not replay interrupted
HTTP requests or turn a failed benchmark into a pass. Monitor task replacements,
restart logs and client failures; process counters reset after a restart.
Messages already accepted by RabbitMQ remain
the broker/consumer's responsibility. Unconfirmed messages are uncertain and are
not replayable from the mock after a crash; there is no local outage buffer.

Stop new HTTP load and drain client requests/capture processing before stopping
or updating the mock. These deployments are an alternative to the outbox contract,
not evidence that the previous one-hour results apply. Perform a smoke, client-side
rate check, reconciliation and explicit broker-failure check before a new hour run.

## Repeat the local resilience proof

After building both images, run:

```sh
python3 deploy/portainer/direct/resilience-smoke.py \
  --official-image ghcr.io/timaday/wiremock-lab-official:20261005-direct-2 \
  --headless-image ghcr.io/timaday/wiremock-lab-headless:20261005-direct-2 \
  --output results/direct-rabbit-resilience-new-run
```

The output directory must be new. This uses an isolated temporary RabbitMQ and
Docker network, not the live PocketHive broker. It checks eight invalid requests
per runtime without a process restart, then all twelve six-second fixture cases
per runtime and every full capture against client hashes. It stops its broker,
checks explicit capture failure and supervisor restart, restores the broker and
repeats the valid requests/capture reconciliation. Containers are stopped and
retained with logs and full capture evidence; there is no automatic prune/removal.
It uses local Docker `on-failure` supervision. Swarm's manifest is checked separately;
this is not a remote Swarm or one-hour performance qualification. The test broker
uses tmpfs and therefore does not prove broker disk/power-loss durability.
