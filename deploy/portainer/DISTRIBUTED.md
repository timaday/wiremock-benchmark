# Distributed WireMock comparison on Swarm

Upload [stack-ghcr-distributed.yml](stack-ghcr-distributed.yml) to Portainer's
Swarm environment. This is the standalone capture-RabbitMQ variant, with explicit
per-service placement for the six-node, 4-CPU/16-GiB-per-node lab. It uses the same
pinned images, backlog, HTTP settings, resource limits and durable capture as
`stack-ghcr.yml`. `render.py` owns both files. No build or Docker secrets are required.

## Placement and runtime selection

Use [example-distributed.env](example-distributed.env), replacing its node names
with the exact hostnames in Portainer's Swarm nodes view:

| Setting | Example placement | Services |
| --- | --- | --- |
| `OFFICIAL_NODE`, `HEADLESS_NODE` | Worker 1 | The selected WireMock |
| `RABBIT_NODE` | Worker 2 | Capture RabbitMQ |
| `ARCHIVE_NODE` | Worker 3 | Both capture archives |
| `MONITORING_NODE` | A manager with spare capacity | Prometheus and Grafana |

Both mocks can use worker 1 because the example explicitly selects only headless:
`OFFICIAL_REPLICAS=0`, `HEADLESS_REPLICAS=1`. To compare official, stop and drain
the headless run first, then set `OFFICIAL_REPLICAS=1`, `HEADLESS_REPLICAS=0` and
update the stack. Use only 0 or 1 for each mock; multiple replicas would share its
local outbox. Both archives stay running to finish draining existing captures.
The inactive mock is intentionally 0/0 and its Prometheus target is down.

Each hostname and both replica counts are required; `LAB_NODE` is unused here.
You may select different nodes for the two mocks, but run one benchmark at a time.
Every named volume remains pinned to its owning service's node. If that node is
unavailable, its service stays pending; this design does not provide shared
storage or automatic data failover. Updates use stop-first order.

This stack does not place PocketHive or provide injector capacity. Arrange its
workers separately, keeping substantial injector load off the active mock node.
Do not assume the managers have spare capacity just because this file does not
place heavy benchmark services there. Monitoring on a manager is a lab choice;
use a different eligible node if the manager is busy or drained.

## Add in Portainer

1. Select the **Swarm** environment, then **Stacks → Add stack**. Give it a new
   name, for example `wiremock-distributed`, and upload the YAML file.
2. Load the example environment file and replace the five node values and both
   passwords. Use a new `CAPTURE_PREFIX`. Keep `CAPTURE_ENABLED=true` and
   `WIREMOCK_ACCEPT_BACKLOG=4096` for the capture-enabled comparison.
3. The example uses ports 19180/19181 (official/headless), 13100 (Grafana),
   29190 (Prometheus), 5674/15674 (capture RabbitMQ). These differ from the old
   stack's defaults so a new stack can be prepared without port collisions.
   Confirm these ports are unused and reachable in your environment.
4. Deploy with image pulls enabled. The example should show headless and all
   five supporting services at 1/1, plus official at 0/0. Verify actual node
   placement, archive consumers and broker connectivity before enabling load.
5. Point PocketHive's headless SUT at `http://SWARM_HOST:19181` (official uses
   19180). Its Work transport still uses PocketHive's own RabbitMQ. This stack's
   RabbitMQ is for WireMock captures, not PocketHive Work.
6. Open `http://SWARM_HOST:13100/d/wiremock-comparison`, selecting the active
   runtime. Run the short load test before another hour; distribution has not
   yet been performance-qualified on your hardware.

The default overlay connects services across nodes; Rabbit and monitoring keep
their internal DNS names. Existing Swarm connectivity must work between nodes,
including TCP/UDP 7946 and UDP 4789, plus TCP 2377 for management. See
[Docker's networking requirements](https://docs.docker.com/engine/swarm/networking/).
Published HTTP ports still use Swarm ingress. The image platforms remain Linux AMD64.

## Existing data

**Do not change the old stack's placement variables to move its data.** Docker's
local volumes are node-local; an identically named volume on another node can be
empty. See [Docker service volumes](https://docs.docker.com/engine/swarm/services/#data-volumes).

The new stack name creates separate volumes and the new queue prefix separates
captures. The old stack and its evidence remain intact. Stop old load and let its
outbox, Rabbit queues and archive drain before testing the new stack, so the two
stacks do not compete for resources. Keep the original volumes for verification.

If existing state must move instead of starting a fresh comparison, stop its
writers after draining, back up the complete volumes, copy them to the selected
nodes and verify the copies before changing placement. SQLite copies must include
their WAL state or use a consistent backup. This file performs no migration or
cleanup. Do not scale the archives while migrating their databases.
