# Capture correlation without changing the HTTP response

Use a new mock and archive build with capture envelope version 2 and set
`CAPTURE_IDENTITY_MODE=STUB_JSON` on the mock. Existing published direct-2 images
do not implement this feature. `BENCHMARK_HEADERS` explicitly selects the old
benchmark admission and URL rules. Broker durability/failure handling is unchanged.

POST this mapping to `/__admin/mappings` through the mock's published HTTP port:
The ready-to-upload file is
[`empty-200-mapping.json`](../deploy/portainer/direct/empty-200-mapping.json).

```json
{
  "id": "3d0f66aa-e397-4d5a-b4ad-dae7f6514208",
  "request": {"method": "POST", "urlPath": "/transaction"},
  "response": {
    "status": 200,
    "fixedDelayMilliseconds": 1000,
    "transformerParameters": {
      "capture": {
        "runId": "work-test-001",
        "correlationJsonPath": "$.correlationId",
        "missingCorrelation": "RECORD_UNCORRELATED"
      }
    }
  }
}
```

POST `{"correlationId":"test-123"}` to `/transaction`. The HTTP response is an
empty 200 after the delay. Each capture has `correlationId: "test-123"` and
`correlationStatus: "PRESENT"`; the generated `requestId` links all three phases.
No `X-Bench-*` headers or `/bench/` URL are needed. No body is inserted into the
HTTP response. With `{}` the response stays empty 200, and capture records an
empty correlation value with status `MISSING`, using a unique internal request ID.

To switch fields while running, PUT the complete updated mapping to
`/__admin/mappings/3d0f66aa-e397-4d5a-b4ad-dae7f6514208`, changing the path to
`$.requestId`. Subsequent requests use that field. Requests already matched retain
their original identity snapshot. Update `runId` here for a new run. There is no
automatic field discovery and no alternative field lookup on extraction failure.

For an optional templated response, add `"transformers":["response-template"]`
and reference the same selector in its body:
`{{jsonPath request.body parameters.capture.correlationJsonPath}}`.
Capture configuration does not require the response-template transformer.

The [contract](CONTRACT.md#capture-identity-and-live-stub-configuration-envelope-version-2)
defines invalid/missing values, selection, admission and schema-version boundaries.
Reapply live mappings after replacing a read-only container. An empty queue or a
generated request ID does not replace client/capture reconciliation by a shared ID.

## Build and verify

`python3 deploy/portainer/direct/build.py --prefix wiremock-dynamic --tag 20261006-1`
builds official, headless and archive images together, using isolated Maven outputs
under `target/direct-maven` to avoid IDE-generated `target/classes` artifacts.
It records exact image IDs in `target/direct-image/images.json`; it does not
publish them or change a running deployment. Choose a new tag for subsequent builds.

Run the real-broker/real-archive test with:

```sh
python3 deploy/portainer/direct/dynamic-smoke.py \
  --images target/direct-image/images.json --output results/NEW-DYNAMIC-RUN
```

It uses both generated dedicated stacks locally with bridge networking and
loopback ports. It verifies empty 200s, missing/malformed input, duplicate business
IDs, live field changes, invalid edit rejection, optional response templating,
full archived bytes and no process restarts. The headless trial also runs the Maven
tests against its isolated RabbitMQ. Containers and evidence are stopped/retained.
This is not a full-rate or AWS Swarm qualification.

For the bounded headless throughput demonstration, run:

```sh
python3 deploy/portainer/direct/dynamic-load.py --output results/NEW-DYNAMIC-LOAD
```

This runs a smoke, changes the live mapping from `$.correlationId` to
`$.requestId`, then offers 1,020 requests/s with empty 200 responses and one-second
delay for a five-minute measured hold. RabbitMQ and the durable archive stay
enabled. The [workload and pass criteria](../tests/perf/gatling/DYNAMIC.md) define
the client throughput, exact capture reconciliation and resource guards. Results
include client CSV, archive database, queue/resource samples and image identities.
Add `--delay-ms 6000` to repeat with six-second responses; the mapping and client
timing checks both use the selected delay.

## Published images

The tested official, headless and archive images were published publicly on
7 October 2026 under `ghcr.io/timaday/wiremock-lab-<runtime>:20261007-dynamic-1`
for `linux/amd64`. Anonymous digest pulls succeeded for all three, and their image
identities match the locally tested builds. Portainer does not need GHCR credentials.
The [publication record](../deploy/portainer/direct/dynamic-image-lock.json)
contains immutable digests and the source revision.

All four `stack-direct-*.yml` files now pin the published mock digests directly;
the dedicated RabbitMQ variations also pin the matching version-2 archive.
Their image references cannot be overridden by stale Portainer image variables.
Load `example-direct.env` or `example-direct-rabbit.env`, which explicitly select
`CAPTURE_IDENTITY_MODE=STUB_JSON`, and fill in your node, broker and storage settings.
Then apply your capture-enabled stub mapping through the WireMock admin API.
Use fresh queues and archive paths for the version-2 envelope. For existing
header-based benchmark bundles, explicitly select `BENCHMARK_HEADERS` instead.

[Published image variables](../deploy/portainer/direct/published-dynamic.env) remain
available for custom Compose files; the bundled stacks use the publication lock
directly. With an external PocketHive broker, its capture consumer must support
version 2; changing the mock image does not upgrade that consumer.
