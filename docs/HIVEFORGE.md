# HiveForge benchmark lab

The `swarm-lab` profile deploys the same seven services as the standalone
Portainer comparison: official/headless WireMock, two archives, RabbitMQ,
Prometheus and Grafana. It consumes the existing public GHCR image digests.
It does not build images, launch load, import PocketHive scenarios or change AWS
network rules.

This is the requested development lab: RabbitMQ uses `benchmark` / `benchmark`,
and Grafana uses `admin` / `benchmark`. These are public fixture values, not
confidential credentials. No Docker secrets or credential files are required.
They initialize fresh volumes; deploying over retained data does not rotate
existing RabbitMQ/Grafana accounts. Use a distinct deployment name from the
existing Portainer stack and ensure its published ports are available.

## HiveForge version and ownership

Checked on September 30, 2026 against the latest published release
[v0.5.9](https://github.com/sepa79/HiveForge/releases/tag/v0.5.9), commit
`44820b7f10f7b05d7206e8909421ede4847b6b1d`, and current `main`
`c2f9ad568763a027eeee7629c16b9279367aa7c1`. Main differs only in documentation.
The older local HiveForge 0.4.5 checkout is not the integration authority.

The root manifest declares contract `0.5`, component `stack`, profile
`swarm-lab`, and actions `deploy`, `update`, `remove`. Deploy/update run the
same Ansible renderer, which writes `/hf/stacks/compose.yml`. HiveForge owns
the Docker/Portainer execution and recorded deployment state. Project actions
never call Docker, SSH, Python or a build tool. HiveForge v0.5.9 handles `remove`
directly from recorded deployment state; the declared remove playbook rejects
direct execution. Volumes are retained. No purge action is declared.

All services use the explicit `LAB_NODE` hostname. Named volumes stay on that
node. The profile needs Docker Swarm and placement capability; it needs no
shared host bind storage. HiveForge still supplies its normal `/hf` action root.
The target must be Linux AMD64, matching the published images.

`ACTIVE_RUNTIME` is a required HiveForge input: `both`, `official`, or `headless`.
Use `official` or `headless` for sequential benchmarks on a memory-constrained
node. The selected mock has one replica and the other has zero; both archives,
RabbitMQ, Prometheus and Grafana remain running. Images, heap limits, fixtures,
volumes and queue names stay identical. This selection belongs to the HiveForge
adapter; the canonical Portainer stack still starts both mocks.

Before switching targets, stop and drain the workload and require zero pending
captures and empty capture queues. Set `ACTIVE_RUNTIME` for the same deployment
profile, run HiveForge `update`, and verify the selected mock is healthy. The
inactive mock's Prometheus target reports down by design. Use `both` to restore
the interactive comparison lab. Unknown or omitted selections fail validation.

`CAPTURE_ENABLED` is also required (`true` or `false`). Use `false` only for a
matched diagnostic baseline; qualification requires `true`. Stop and drain load
and captures before changing it. HiveForge recreates the selected mock with the
explicit setting; retained outbox/archive volumes remain unchanged.

## Install HiveForge on HFM

The [HFM installer](../deploy/hiveforge/hfm-install.yml) pins both the service
and action runner to the verified v0.5.9 image digest. It uses the upstream
Lite installation shape, stores runtime data at `/opt/hiveforge`, and pins
the service to an explicit Swarm manager. It creates no Docker secrets.
HiveForge itself generates its normal API token in its runtime directory;
the benchmark's public fixture credentials are separate.

On the selected HFM manager, after confirming port 3000 is free and there is
no existing HiveForge installation to preserve:

```sh
test "$(docker info --format '{{.Swarm.ControlAvailable}}')" = true
export HIVEFORGE_NODE="$(docker info --format '{{.Name}}')"
sudo mkdir -p /opt/hiveforge
docker stack config -c deploy/hiveforge/hfm-install.yml >/dev/null
docker stack deploy -c deploy/hiveforge/hfm-install.yml hiveforge
curl --fail http://hfm:3000/health
```

These commands assume this repository is available on that manager. Connect
the release's stdio MCP client to `http://hfm:3000` as documented
[upstream](https://github.com/sepa79/HiveForge/blob/v0.5.9/docs/install/mcp-clients.md).
Port 3000 is the REST endpoint, not an HTTP MCP endpoint. No global Codex
configuration change is needed for a one-session connection. Per the operator's
instruction, this lab task does not use HiveGate.

The operator installed HiveForge on HFM on September 30, 2026. The retained
project registry initially prevented startup: its `hivemind` entry used the
obsolete `source: github`. After backing up the registry and changing that
value to `https-git`, the public health endpoint returned `status: ok` and
version `0.5.9`; this was independently checked from the workstation. This
proves control-plane process health, not benchmark deployment or MCP access.
The existing local-image `hiveforge-mcp` service has not been qualified against
v0.5.9. Use the release-matched stdio client described above.

Existing runtime directories also need
`capabilities.managedRoot.bindSourceRoot: /opt/hiveforge` in the current
environment's `environments.yaml`, matching the host directory mounted at `/hf`.
Without it the action runner mounts incorrect host paths and fails before Ansible
starts. Back up the file before modifying it, validate it with HiveForge's
environment loader, and restart the HiveForge service after saving.

## HFM deployment verification

On September 30, 2026, HiveForge MCP deployed revision
`6fb4d5a6cfe95b1d5e00415da25522f8a86563e6` as `wiremock-hiveforge` on
`swarm-manager`. All seven services reached `1/1`. The public HTTP smoke test
passed all 24 combinations (four sizes, three templates, two runtimes), with
six-second responses and exact response bodies. Monitoring reported zero HTTP
errors, 72 confirmed capture events, no pending captures, and two drained queues
with one archive consumer each. All 19 queries in the 17-panel Grafana dashboard
returned data. See the [HFM validation record](../deploy/hiveforge/hfm-validation-2026-09-30.json).

During startup, the host `/home` filesystem filled and libvirt paused HFM.
The VM's Docker disk was copied through libvirt to the dedicated VM filesystem;
both live and persistent disk references were verified before resuming. The
original disk was retained and no caches were deleted. The destination had about
17 GiB free after recovery. Libvirt still reported the earlier `vdb: no space`
error, although the VM remained running and the subsequent HTTP/capture checks
passed. This verification is a deployment smoke test; no HFM endurance run or
remote archive-body integrity check was performed.

The legacy environment id `hiveforge-swarm-lab` also prevents
`refresh_environment`, whose detector returns `swarm`. This remains an explicit
configuration issue; the verified deployment used the existing environment.

After that smoke check, Grafana exited with code 137 and the operator confirmed
`OOMKilled=true`. The original 512 MiB container limit was insufficient. The
canonical stack now gives Grafana 1 GiB. That correction was deployed at
`2cf5fe49`; Grafana and both mock health checks passed after recovery. The explicit
`restart_policy: none` remains unchanged so failures remain visible.

During the subsequent headless endurance run, the 1 GiB Grafana task also exited
with code 137. HiveForge confirmed its missing replica; it did not expose the
stopped container's OOM flag. WireMock, Prometheus, RabbitMQ and both archives
continued running. The canonical stack now sets `GOMEMLIMIT=512MiB` for Grafana
to make Go collect below its container ceiling. This mitigation needs deployment
and observation on HFM before it can be called a verified fix; no mock settings
or capture settings change.

Full-rate HFM attempts subsequently exposed guest memory exhaustion. Pausing the
separate HFM PocketHive installation increased available guest memory from
147 MiB to 6.6 GiB. After the official retry, its idle JVM retained heap and only
3.5 GiB remained available, motivating the explicit single-runtime selection.
The official retry still failed: 91,472 of 91,800 results, connection-reset logs,
and 794.3 collected results/s in the measurement window. The cause of the resets
is not established. No HFM one-hour qualification passed; see the
[retry evidence](../tests/perf/pockethive/hfm-retry-20260930/verdict.json).

Revision `399e3d6` subsequently deployed with `ACTIVE_RUNTIME=headless`: official
reached `0/0`, while headless and all five support services remained `1/1`.
The fresh headless short run returned all 91,800 responses with correct client
hashes and no missing IDs. Its measured client collection rate was 965.4/s,
below the 1,000/s gate; header latency p99 was 7,752ms. Pending captures peaked
at 60,711 sampled events, then drained to zero with 275,400 new confirmations
and empty RabbitMQ queues. Archive body reconciliation remains unverified.
The resource guard did not trip (minimum sampled workstation available memory
4.177 GiB), and the services remained running. This does not establish guest
memory stability or explain the throughput shortfall. The load swarm was
stopped and removed; headless-only deployment remains active. No HFM one-hour
hold was started.

The subsequent throughput fix routes inserts and confirmed deletions through
one outbox writer and reuses the publisher's read connection, retaining FULL/WAL
durability. It adds capture-stage timing metrics and fresh PocketHive bundles
that retain worker-hop timings. Updated official/headless GHCR images are pinned
in the image lock. The local headless Gatling check passed 1,019.8 completions/s
for a 60-second measured interval, with 6,048ms p99 and all 183,600 measured
capture events reconciled. Both runtimes passed broker-outage/process-kill
recovery checks. This is local validation; HFM reruns and one-hour qualification
remain pending. See the [validation record](../tests/perf/pockethive/hfm-throughput-20260930/validation.json).

## Deploy through HiveForge

After these source files are committed and pushed:

1. Register `https://github.com/timaday/wiremock-benchmark.git` as project
   `wiremock-benchmark`, approving the exact ref you intend to deploy.
2. Allow that project on the selected environment with profile `swarm-lab`
   and actions `deploy`, `update`, `remove`.
3. Set these five non-secret runtime environment values for that profile:

   ```text
   LAB_NODE=your-swarm-node-hostname
   CAPTURE_PREFIX=wiremock-hiveforge-01
   ACTIVE_RUNTIME=official
   CAPTURE_ENABLED=true
   WIREMOCK_ACCEPT_BACKLOG=4096
   ```

   `WIREMOCK_ACCEPT_BACKLOG` is required and must be a positive integer. It sets
   both mocks' accept queues; Linux caps the effective value at `net.core.somaxconn`.
   Stop and drain load/capture before changing it. The pinned headless image
   implements the setting; old headless images ignore it. Local component checks
   passed, but this setting has not been deployed or load-tested on HFM.

4. Validate requirements. Start component `stack`, action `deploy`, profile
   `swarm-lab`, with the approved Git ref and an explicit deployment name, for
   example `wiremock-hiveforge`.
5. Inspect the operation and recorded deployment diagnostics. Require the selected
   mock(s) and all five support services running, selected mock metrics targets up,
   capture broker connections established and no capture errors before load.

Use the selected HiveForge environment's UI or its MCP connection.
The repo does not register itself, grant policy, take over the existing
Portainer stack, or deploy automatically. Use `update` for the same recorded
deployment slot; removal is a separate explicit lifecycle action.

Apart from the explicit runtime selection, the profile fixes the canonical Portainer defaults: official `19080`, headless
`19081`, Grafana `13000`, Prometheus `29090`, Rabbit AMQP `5673`, management
`15673`, with capture enabled. Other Portainer environment overrides are not
part of this profile. The Grafana dashboard path is `/d/wiremock-comparison`.

For PocketHive load generation, use [the bundle guide](../tests/perf/pockethive/README.md).
Those bundles separately require Artemis work transport and a Redis evidence
sink. The HiveForge lab includes its own capture RabbitMQ and does not implement
the proposed postprocessor reconciliation integration.

## Source and local validation

`deploy/portainer/render.py` owns the service definitions. The offline adapter
`deploy/hiveforge/generate.py` derives its Ansible template from
`deploy/portainer/stack-ghcr.yml`, fixing the declared lab credentials/defaults
and retaining only the node and capture-prefix substitutions. It must fail on
an unknown required input. No second hand-maintained Compose definition exists.

After changing the canonical stack, regenerate in this order:

Local adapter tests require Python with PyYAML and Jinja2, plus the Docker CLI.

```sh
python3 deploy/portainer/render.py --registry-lock deploy/portainer/image-lock.json
python3 deploy/hiveforge/generate.py
python3 -m unittest discover -s deploy/hiveforge/tests -p 'test_*.py'
```

The generated template ships with the adapter so HiveForge needs only its guaranteed
Ansible built-ins. Local rendering is development proof, not a live HiveForge
deployment. Actual environment policy, node availability and ingress remain
checks for the selected deployment environment.

The [local validation record](../deploy/hiveforge/validation-2026-09-30.json)
records the exact v0.5.9 runner image digest. Its real project-manifest loader,
Ansible renderer and Docker Stack parser passed. A second render was unchanged;
missing node/prefix, unsupported profile and an invalid prefix were rejected.
Three adapter checks passed, including complete parsed-stack parity with the
canonical Portainer lab. No target environment was deployed during these checks.

The [runtime-selection validation](../deploy/hiveforge/runtime-selection-validation-2026-09-30.json)
records the later four adapter checks and real v0.5.9 Ansible renders for all
three selections. Docker Stack parsed each result; missing and invalid selections
were rejected. This is local validation of the prepared change, not evidence that
single-runtime operation fixes the connection resets or passes endurance.
