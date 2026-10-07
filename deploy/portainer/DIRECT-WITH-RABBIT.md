# Direct capture with a dedicated broker and archive

Upload `stack-direct-headless-rabbit.yml` or `stack-direct-official-rabbit.yml`
as a **named Docker Swarm stack** in Portainer. Load `example-direct-rabbit.env`
and replace its node, storage and password placeholders. Each stack contains
one direct-capture mock, a dedicated RabbitMQ and the existing archive consumer.
Both files pin the published `20261007-dynamic-1` mock and matching version-2
archive directly, using [the publication lock](direct/dynamic-image-lock.json).
Old `HEADLESS_DIRECT_IMAGE`, `OFFICIAL_DIRECT_IMAGE` and `ARCHIVE_IMAGE` environment
values do not override those pins. The example selects `STUB_JSON`; see
[dynamic capture](../../docs/DYNAMIC-CAPTURE.md) for live per-stub correlation settings.
The generated YAML is self-contained; no checkout, Docker secrets, configuration
file upload or image build is needed. Existing public GHCR images are pinned.

PocketHive can run on your laptop and target the published HTTP port. It keeps
its own workload broker. WireMock publishes captures to `rabbit:5672` on this
stack's private overlay; the archive saves complete captures before acknowledging
them. No connection from AWS to your laptop is required. The broker AMQP port is
not published; its management UI is published for diagnostics.

## Storage and placement

Set `LAB_NODE` to the mock worker and `RABBIT_NODE` / `ARCHIVE_NODE` to the workers
with the prepared storage. On 4-core, 16-GiB nodes, dedicate one node to the mock;
the broker and archive may share a second node. Limits are mock 4 CPU / 4 GiB,
broker 2 CPU / 2 GiB and archive 2 CPU / 1 GiB. This is not a throughput guarantee.

`RABBIT_DATA_DIR` and `ARCHIVE_DATA_DIR` must be existing, separate, absolute
directories on **local SSD or EBS-backed filesystems on their selected nodes**.
Do not use EFS/NFS for these paths, including indirectly through symlinks or
parent mounts: the archive uses SQLite WAL. Verify each path with `findmnt -T`
and `df -h` before deployment. Prepare the broker directory writable by UID/GID
999:999; the existing archive image runs as root. Use fresh empty directories,
not the unhealthy PocketHive database. Reserve at least 12 GiB free for the
broker and 30 GiB for the archive before an hour; actual payloads determine growth.

The broker's hostname and node name are fixed at `rabbit` / `rabbit@rabbit`.
Both stateful services have one replica, fixed placement and stop-first updates.
Do not scale them out or repoint their directories to recover a missing node.
This is persistent single-node storage, not an HA RabbitMQ cluster. Files survive
task replacement on the same storage, not loss of its disk. Reusing a directory
between stacks or both variants is unsupported.

## Settings and protection

Generate `RABBIT_PASSWORD` with `openssl rand -hex 24`. This variant explicitly
accepts only 32–128 hexadecimal characters so the same value is safe in both its
AMQP URL and boot definitions. User `benchmark` and vhost `/` are fixed. Credentials
are normal environment variables, visible to deployment administrators. They
are lab configuration, not Docker secrets. Restrict the management port to your
VPN/admin network. Changing an environment password is not a supported password
rotation procedure for an existing database.

The broker imports a queue policy **before accepting load**, covering all queues
on this dedicated broker. `CAPTURE_QUEUE_MAX_BYTES` limits ready message body
bytes; `CAPTURE_QUEUE_MAX_MESSAGES` also limits ready message count. Overflow is
`reject-publish`, with no TTL/drop-head policy. Defaults in the example are 1 GiB
and 200,000 messages. A rejected capture fails the mock/run explicitly; Swarm
restarts it. This retains already accepted records but does not make an overloaded
run valid. In-flight publications can slightly exceed the limit.

The disk alarm uses `RABBIT_DISK_FREE_LIMIT_BYTES` (example 5 GiB) and memory alarm
uses an absolute 1 GiB, below the 2 GiB container limit. Queue limits exclude
unacknowledged messages and storage overhead, and do not limit archive growth.
Alarms/queue limits cannot guarantee a filesystem will never fill. Stop load if
ready/unacknowledged messages trend upward or archive disk reserve approaches
5 GiB. Retain/export evidence between runs; nothing deletes it automatically.

Classic queues are explicit because this variant uses the existing classic-queue
archive image. Broker boot configuration and policies come from
`direct/rabbit-bootstrap.sh`, embedded by the renderer into the YAML. Its JSON
definitions are RabbitMQ's required import format; the Portainer file is YAML.
The bootstrap validates inputs without printing credentials, writes temporary
configuration and execs the upstream RabbitMQ entrypoint. There is no new image.

RabbitMQ health checks the application and local AMQP availability. Disk/memory
alarms block publishers; they are deliberately not restart triggers. Archive health checks
that the database exists and is writable; it is **not** proof of consumption or
reconciliation. Swarm does not order readiness: mocks may restart until RabbitMQ
is ready. Wait for stable tasks, no alarms and one queue consumer before load.

## Run and verify

With the example ports, target `http://<AWS-swarm-host>:19381` for headless or
`:19380` for official. RabbitMQ UI is `http://<AWS-swarm-host>:15675`, with user
`benchmark`. Change its port if deploying both variations simultaneously.
Queue names are `<CAPTURE_PREFIX>.headless` / `.official`. Apply a capture-enabled
mapping for `STUB_JSON`, choosing the response delay in that mapping. For the
built-in six-second `/bench/...` fixtures and existing benchmark bundles, explicitly
set `CAPTURE_IDENTITY_MODE=BENCHMARK_HEADERS`. Backlog 4096, full bodies and template
behavior are retained.

Start with a short smoke, then a full-rate short run. Confirm the queue has one
consumer, capture errors remain zero, no tasks restart, and queues drain. The
archive is `<ARCHIVE_DATA_DIR>/events.db`. Before copying it, stop load, drain
requests and queues, then stop the archive; alternatively use SQLite's backup API
to obtain a consistent live copy. Do not copy just the live database without its
WAL. Use `tools/read_capture.py` and the benchmark reconciliation tools to check
IDs, phases and body hashes against PocketHive's client results.

At 1,000 HTTP requests/s, expect approximately 3,000 capture events/s. An empty
queue or publisher confirmations alone do not prove all client results were
captured. `SEND_COMPLETED` is a WireMock callback, not proof of delivery. This
variation retains the [direct capture failure contract](DIRECT-RABBIT.md): no
local mock outage buffer or retry of uncertain events. A new full-hour run is
required to qualify this deployment.

References: [RabbitMQ definition import](https://www.rabbitmq.com/docs/3.13/definitions),
[queue limits](https://www.rabbitmq.com/docs/3.13/maxlength),
[disk alarms](https://www.rabbitmq.com/docs/3.13/disk-alarms),
[SQLite WAL filesystem requirements](https://www.sqlite.org/wal.html).

## Repeat the local check

The 2026-10-06 [verification record](direct/dedicated-verification.json) reports
48 requests and 144 reconciled captures across both runtimes, including 72 events
retained across broker restarts. Both one-message overflow trials retained the
accepted record and terminated the mock with exit 70. Fourteen Portainer tests
and six HiveForge regression tests passed; generated stacks reproduced exactly.
Earlier smoke attempts caught management-statistics timing assumptions and a
bootstrap temporary-file permission issue. The final run includes their fixes;
all attempt evidence is retained under `results/direct-dedicated-20261006*`.

Run `python3 deploy/portainer/direct/dedicated-smoke.py --output results/NEW-DIRECT-RUN`
after pulling the image digests in the stack/example environment. It tests both
variants sequentially with fresh local directories, a Docker bridge, loopback
ports and the stack's CPU/memory limits. It verifies all twelve six-second cases,
archives their full bodies, queues a second set across a broker restart, then
checks queue overflow fails capture with exit 70 and retains the accepted record.
The temporary one-message policy is confined to the disposable test broker.
It stops its own containers and retains containers, broker data, archives and logs.
This checks application/storage behavior; it is not an AWS Swarm deployment,
power-loss durability test or 1,000 requests/s qualification.
