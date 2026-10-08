# Official WireMock without capture

Upload `stack-official-no-capture.yml` into a new named Portainer Swarm stack.
Set `LAB_NODE` to the Docker hostname of the selected Linux AMD64 worker.
Optional variables: `OFFICIAL_PORT=19480` and `WIREMOCK_ACCEPT_BACKLOG=4096`.
Choose a free published port if another stack already uses it.

This uses our published image based on official WireMock 3.13.2, including the
benchmark mappings and metrics extension. `CAPTURE_ENABLED=false` disables capture
and broker connections. There are no RabbitMQ, archive, Redis or monitoring
services, persistent volumes, credentials or external networks to configure.
The image is pinned by digest and needs no new build.

The mock has a read-only root filesystem and a 64 MiB temporary filesystem,
4 CPU / 4 GiB limits, a 3 GiB maximum Java heap, backlog 4096 by default,
128 container threads and 64 asynchronous response threads. Request journalling
and per-request logging are disabled. Health checks, bounded container logs and
restart-on-failure remain enabled. These settings are not a 1,000 requests/s
qualification on your host.

For ordinary local Docker Compose, from the repository root:

```sh
export LAB_NODE="$(hostname)"
docker compose -f deploy/portainer/stack-official-no-capture.yml up -d
```

Swarm honours `LAB_NODE` placement; ordinary Compose runs on the selected Docker
host. Portainer deployment does not require running this command.

Check `http://YOUR_HOST:19480/__admin/health`. Existing `/bench/...` fixtures are
bundled; custom stubs can be added using the WireMock admin API. For example,
an empty HTTP 200 response with a six-second asynchronous delay:

```sh
curl --fail-with-body -X POST 'http://YOUR_HOST:19480/__admin/mappings' \
  -H 'Content-Type: application/json' \
  --data '{"request":{"method":"POST","urlPath":"/demo/empty"},"response":{"status":200,"fixedDelayMilliseconds":6000}}'

curl -sS -o /dev/null -w 'status=%{http_code} seconds=%{time_total}\n' \
  -X POST 'http://YOUR_HOST:19480/demo/empty'
```

Custom response templates use `"transformers":["response-template"]` in the
response definition, as with the capture-enabled image. Capture headers and
capture transformer parameters are unnecessary. Runtime mapping changes are
in-memory and must be reapplied after task replacement. Keep the admin endpoint
on your trusted lab network.

This is a capture-off performance baseline. It cannot supply captured evidence
or pass capture reconciliation. Deploy it separately from the existing capture
stack so the retained RabbitMQ queue and archive files remain available.
