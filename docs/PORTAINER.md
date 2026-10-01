# Portable WireMock comparison on Docker Swarm

This deployment contains official and headless WireMock, durable RabbitMQ capture,
two independent archives, Prometheus and a provisioned Grafana comparison dashboard.
It includes no load generator. The canonical 96-case fixture catalogue is baked
into both mock images. Select delay, size and template through the request URL.

## Deployment contract

`deploy/portainer/render.py` owns the generated stack files. `stack.yml` includes
a dedicated RabbitMQ. `stack-pockethive.yml` uses the explicitly configured existing
PocketHive RabbitMQ URI and creates no broker. Each runtime has its own durable
capture queue, outbox and archive. The user must supply a distinct queue prefix.
The existing archive remains the capture consumer in both variants.

Images contain all configuration and fixtures. Stack deployment requires images
already available on the selected node or in a reachable registry; Portainer/Swarm
does not build them. All services are pinned to the required `LAB_NODE` hostname
because named volumes are local. Moving the node requires explicit volume migration.
No host bind mounts or local source checkout are required on the deployment node.

The same capture extension owns telemetry in both runtimes. Existing JSON `/metrics`
on port 8081 is preserved. New `/prometheus` exposes completed HTTP requests, error
responses, server timing histogram, JVM heap/nonheap, process CPU time, thread count,
GC collections/time and existing capture delivery counters. Only `/bench/` requests
are counted. Counters reset on restart. Histogram duration is WireMock server timing,
including configured delay; it is not the load generator's end-to-end latency.
The histogram has fixed buckets; quantiles are estimates. No request IDs are labels.
Metrics remain available when durable capture is disabled.

Grafana is observational. It cannot establish exact capture reconciliation or a
benchmark pass. The external-broker variant does not scrape or reconfigure the
shared broker. Its RabbitMQ panels show no data; mock/capture metrics still work.
No Docker socket or privileged host-metrics agent is required. JVM process CPU and
heap are shown; container RSS/host CPU are outside this dashboard's scope.

## PocketHive postprocessor

The deployed PocketHive 0.15.35 Rabbit adapter decodes the canonical WorkItem JSON
envelope. These capture messages are zlib-compressed CaptureEvent JSON, with three
phases per HTTP exchange. The postprocessor aggregates WorkItem outcomes and emits
metrics/ClickHouse outcomes; it does not currently reconcile raw capture phases,
expected requests, duplicate event IDs, body hashes or missing completions.

For that future path, use PocketHive's RabbitMQ as requested. A decoder/reconciler
must durably correlate run/request IDs and deduplicate event IDs, compare against
client evidence, then publish canonical WorkItems to a dedicated postprocessor queue.
Acknowledgement must follow durable processing. This stack does not implement or
claim that integration. Do not attach a postprocessor as a competing consumer to
an archive queue: it would take only a share of the events. Independent consumers
need separate bound queues and an explicit publication topology change; the existing
capture publisher uses the default exchange and one declared queue.

## Sources

- [Portainer stack upload and environment variables](https://docs.portainer.io/user/docker/stacks/add)
- [Portainer custom registry authentication](https://docs.portainer.io/admin/registries/add/custom)
- [GHCR authentication and pulling by digest](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [RabbitMQ 3.13 Prometheus endpoints](https://www.rabbitmq.com/docs/3.13/prometheus)
- [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/)


## Deploy the published GHCR images

The six baked images use `ghcr.io/timaday/wiremock-lab-<component>:20260930`,
where component is `official`, `headless`, `archive`, `rabbit`, `prometheus` or
`grafana`. These are Linux AMD64 images. The two ready-to-upload manifests pin
every image to its registry digest; no local build or source checkout is needed:

- [`stack-ghcr.yml`](../deploy/portainer/stack-ghcr.yml): dedicated RabbitMQ.
- [`stack-ghcr-pockethive.yml`](../deploy/portainer/stack-ghcr-pockethive.yml):
  existing PocketHive RabbitMQ, using `POCKETHIVE_RABBIT_URI`.

All six packages are public, and anonymous access to each pinned manifest and
image configuration was verified. Portainer does not need GHCR credentials.

Upload the selected GHCR manifest using **Stacks → Add stack → Upload**, then set
the variables described in steps 4–5 below. `LAB_IMAGE_PREFIX` and `LAB_TAG` are
ignored by these digest-pinned manifests. Allow image pulls. Set `LAB_NODE` to an
AMD64 Swarm node with capacity for the service limits below.

[`image-lock.json`](../deploy/portainer/image-lock.json) records published digests,
platforms and registry verification. The image source label links the repository.

## Build your own images

1. On a Linux machine with Docker, run `./deploy/portainer/build.sh` from this
   repository. This builds six tagged images and runs the Java tests. No local
   Java/Maven installation is needed. The supplied image names use `wiremock-lab-<component>:20260930`. Set `LAB_IMAGE_PREFIX` and `LAB_TAG` before building to use
   your own registry namespace/version.
2. Make all six images available on the node selected by `LAB_NODE`. Building on
   that node is sufficient. For another node, use
   `./deploy/portainer/export-images.sh /large-disk/wiremock-images.tar.gz`, transfer
   the archive, then `docker image load -i wiremock-images.tar.gz`. The export keeps
   the uncompressed archive too, so allow space for both. Alternatively publish the
   images to your registry and set the corresponding prefix/tag in Portainer.
3. In Portainer select the **Swarm** environment, **Stacks → Add stack → Upload**.
   Upload `deploy/portainer/stack.yml`, or `stack-pockethive.yml` when using the
   existing PocketHive broker. The files contain no `build`, profiles or host paths.
4. Load variables from `deploy/portainer/example.env`, replace placeholders and set
   `LAB_NODE` to the exact hostname shown by `docker node ls`. Set a unique
   `CAPTURE_PREFIX` for this stack. Supply a URL-safe standalone Rabbit password
   (random hex works) and a Grafana password. For the PocketHive variant, supply
   `POCKETHIVE_RABBIT_URI` instead of a standalone Rabbit password. URI credentials
   and vhost names must be percent-encoded. The AMQP endpoint must be reachable
   from the Swarm overlay; an HTTP PocketHive ingress URL is not an AMQP endpoint.
5. Deploy. Disable image re-pull when using images loaded locally without a registry.
   All services should reach 1/1. Before load, the dashboard must show both mock
   targets up and both capture broker connections at 1. Swarm does not sequence
   services with Compose `depends_on`; publishers retain captures while the
   configured broker starts, using the existing durable outbox protocol.

Default published endpoints on a reachable Swarm node:

| Service | Address |
| --- | --- |
| Official HTTP | `http://HOST:19080` |
| Headless HTTP | `http://HOST:19081` |
| Grafana dashboard | `http://HOST:13000/d/wiremock-comparison` |
| Prometheus | `http://HOST:29090` |
| Standalone Rabbit management | `http://HOST:15673` (user `benchmark`) |
| Standalone Rabbit AMQP | `HOST:5673` |

Ports are configurable in the environment file. Grafana uses `GRAFANA_USER`
(default `admin`) and your supplied password. Rabbit/Grafana credentials initialise
on first boot; changing environment variables does not rotate existing accounts
in retained volumes. The stack's HTTP/admin endpoints have the same trusted-network
scope as the local benchmark; expose these ports only to intended test clients.

The dashboard is pre-provisioned under the **WireMock** folder with both runtimes
selected. Its datasource is internal `http://prometheus:9090`. The external-broker
variant keeps the shared broker untouched and still archives each runtime's queue;
it does not automatically deploy or connect a PocketHive postprocessor.

## Point a load generator at it

POST to `/bench/<template>-<bytes>-<delay-ms>`, for example
`/bench/json-51200-6000`. Templates: `static`, `json`, `text`. Sizes: 1024, 5120,
10240, 51200 bytes. Delays: 0, 1000, 1500, 2000, 3000, 4000, 5000, 6000 ms.
All 96 mappings come from `tools/fixtures.py` and are identical in both images.

Every captured request must include `X-Bench-Run` (a unique run identifier) and
`X-Bench-Id` (a unique request identifier). Use exactly 29 ASCII characters for the
request ID to preserve the declared dynamic response size. Set Content-Type to
`application/json` and construct the desired exact-size body. Missing correlation
headers on `/bench/` terminate the capture-enabled mock, per the durable-capture
contract. Set `CAPTURE_ENABLED=false` explicitly for a hook-off test; HTTP/JVM
metrics still operate. Archive services remain idle in that mode.

A portable HTTP smoke check generates exact request bytes, validates every
response, and checks the six-second minimum delay:

```sh
python3 deploy/portainer/smoke.py \
  --official-url http://HOST:19080 --headless-url http://HOST:19081 \
  --output smoke.json
```

For a fair comparison, send the same mix and arrival rate to one runtime at a time.
At 1,000 requests/s and six-second responses, budget roughly 6,000 in-flight HTTP
requests. Record the generator's real response latency and errors alongside the
server dashboard. Capture archives are named volumes `<STACK>_official-archive`
and `<STACK>_headless-archive`, each containing `events.db`. Outboxes, Rabbit data,
Prometheus history and Grafana state have separate volumes. Removing the Swarm
stack leaves those volumes intact. No evidence deletion is automated.

Mocks are each capped at 4 CPU/4 GiB with a 3 GiB heap. Each archive is capped at
2 CPU/768 MiB; Rabbit at 2 CPU/1.5 GiB; Prometheus at 1 CPU/768 MiB; Grafana at
1 CPU/1 GiB. Grafana sets `GOMEMLIMIT=512MiB` so Go starts reclaiming memory
below the container ceiling, leaving room for non-Go allocations. This is a
[soft Go runtime limit](https://go.dev/doc/gc-guide#Memory_limit), not an RSS cap
or a guarantee against OOM. The earlier 512 MiB container limit caused a confirmed
OOM kill; a later 1 GiB task exited with code 137 during the HFM endurance run.
The new environment setting requires a stack update and live verification.
Failures remain visible with `restart_policy: none`. Prometheus retains
up to seven days/2 GiB. Full captures accumulate
until explicitly archived/removed by the operator; plan disk capacity for the hold.

## Verification and scope

`python3 -m unittest discover -s deploy/portainer -p 'test_*.py'` checks required
credential interpolation with the actual Swarm parser and verifies that the
PocketHive variant neither creates a broker nor accepts an absent external URI.
`render.py` requires PyYAML for maintainer regeneration; pre-generated deployment
files and image builds do not require PyYAML on the deployment host.

The dashboard adds observational metrics to the capture extension. The earlier
PocketHive hour results belong to their recorded source/image versions; they do
not constitute a fresh endurance qualification of these instrumented lab images.
See [the local Swarm validation record](../deploy/portainer/validation-2026-09-30.json):
24 exact client cases, 72 full capture events, both metrics targets and all
configured dashboard queries passed. Capture-off HTTP/JVM metrics also passed
for both runtimes. Six Java tests, 30 existing Python tests and two Swarm parser
regression tests passed. Browser visual inspection was unavailable. The existing
PocketHive broker variant was parsed, but was not deployed against the shared broker.
The temporary validation stacks were removed; their evidence volumes remain.

To verify a fresh smoke stack, run this on its selected Swarm node (the archive
volumes must already exist locally), with `GRAFANA_USER` and `GRAFANA_PASSWORD`
set in your shell environment:

```sh
python3 deploy/portainer/verify-smoke.py \
  --stack YOUR_STACK --broker-mode standalone \
  --prometheus-url http://HOST:29090 --grafana-url http://HOST:13000 \
  --results smoke.json --output smoke-validation.json
```

Use `--broker-mode pockethive` for the existing-broker variant. This smoke verifier
expects a fresh pair of mocks with exactly the 24 smoke requests and no other load.
It checks full archived body bytes and hashes, three phases per exchange, native
HTTP/heap/capture metrics, provisioned dashboard identity and live panel queries.
It is separate from the load benchmark's client-CSV qualification verdict.
