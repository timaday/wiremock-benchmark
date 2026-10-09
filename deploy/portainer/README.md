# WireMock comparison stack

Use [the deployment guide](../../docs/PORTAINER.md) for Docker Swarm / Portainer.

- `stack-official-five.yml`: five upstream official WireMocks on ports 19001–19005,
  plus Nginx on 19081 with `/mock-1/` through `/mock-5/` routing. Retains our JVM/HTTP
  tuning, with no custom extensions or baked mappings. See
  [the five-instance guide](OFFICIAL-FIVE.md) for per-instance node placement.
- `stack-official-no-capture.yml`: one official WireMock with bundled mappings,
  capture disabled, no broker and no persistent storage. See
  [the capture-off guide](OFFICIAL-NO-CAPTURE.md).
- `stack-ghcr.yml`: ready-to-upload stack with GHCR image digests and its own RabbitMQ.
- `stack-direct-headless-rabbit-monitored.yml` / `stack-direct-official-rabbit-monitored.yml`:
  one mock, dedicated RabbitMQ, archive, Prometheus and provisioned Grafana dashboard.
  All persistent directories are environment-configured local bind mounts. See
  [the dedicated guide](DIRECT-WITH-RABBIT.md), `example-direct-rabbit.env` and
  `example-direct-monitoring.env`.
- `stack-direct-headless.yml` / `stack-direct-official.yml`: one filesystem-free
  mock per stack, publishing directly to PocketHive RabbitMQ; requires new images.
  See [the direct-capture guide](DIRECT-RABBIT.md) and `example-direct.env`.
- `stack-ghcr-distributed.yml`: separate node placement and explicit mock replica counts;
  see [the distributed guide](DISTRIBUTED.md) and `example-distributed.env`.
- `stack-ghcr-pockethive.yml`: GHCR stack using the existing PocketHive RabbitMQ.
- `image-lock.json`: published image references and verification evidence.
- `stack.yml`: both mocks, two capture archives, RabbitMQ, Prometheus and Grafana.
- `stack-pockethive.yml`: use an explicit existing PocketHive RabbitMQ URI.
- `build.sh`: bake fixtures and monitoring configuration into six images.
- `example.env`: deployment inputs, with placeholder credentials.
- `smoke.py` and `verify-smoke.py`: exact-body, capture and monitoring checks.
- `render.py`: canonical owner of generated stacks and monitoring configuration.

From the repository root, regenerate the pinned stacks using
`python3 deploy/portainer/render.py --registry-lock deploy/portainer/image-lock.json`.
All six GHCR packages are public; Portainer needs no registry token. Published images are
Linux AMD64; single-node variants require `LAB_NODE`, and the distributed variant
requires explicit per-service hostnames.
