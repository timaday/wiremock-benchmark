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

## Deploy through HiveForge

After these source files are committed and pushed:

1. Register `https://github.com/timaday/wiremock-benchmark.git` as project
   `wiremock-benchmark`, approving the exact ref you intend to deploy.
2. Allow that project on the selected environment with profile `swarm-lab`
   and actions `deploy`, `update`, `remove`.
3. Set these two non-secret runtime environment values for that profile:

   ```text
   LAB_NODE=your-swarm-node-hostname
   CAPTURE_PREFIX=wiremock-hiveforge-01
   ```

4. Validate requirements. Start component `stack`, action `deploy`, profile
   `swarm-lab`, with the approved Git ref and an explicit deployment name, for
   example `wiremock-hiveforge`.
5. Inspect the operation and recorded deployment diagnostics. Require all seven
   services running, both mock metrics targets up, capture broker connections
   established and no capture errors before generating load.

Use the selected HiveForge environment's UI or its MCP connection.
The repo does not register itself, grant policy, take over the existing
Portainer stack, or deploy automatically. Use `update` for the same recorded
deployment slot; removal is a separate explicit lifecycle action.

The profile fixes the canonical Portainer defaults: official `19080`, headless
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
