# Five upstream WireMocks

Upload `stack-official-five.yml` to a new named Portainer Swarm stack. It uses
only upstream `wiremock/wiremock:3.13.2`, pinned to its verified image digest.
There are no custom image builds, extension jars, capture workers, brokers,
baked mappings, persistent volumes or external networks.
The same file includes upstream Nginx on port **19081**, routing all five mocks.

Set these Portainer stack variables to the Docker hostnames of your chosen nodes:

| Variable | Service | Published HTTP port |
| --- | --- | --- |
| `WIREMOCK_1_NODE` | `wiremock-1` | 19001 |
| `WIREMOCK_2_NODE` | `wiremock-2` | 19002 |
| `WIREMOCK_3_NODE` | `wiremock-3` | 19003 |
| `WIREMOCK_4_NODE` | `wiremock-4` | 19004 |
| `WIREMOCK_5_NODE` | `wiremock-5` | 19005 |

Also set `NGINX_NODE` to the Docker hostname selected for Nginx. Its limit is
2 CPU / 512 MiB; allow headroom if sharing a mock's node.

| Nginx URL prefix | Destination |
| --- | --- |
| `http://HOST:19081/mock-1/` | `wiremock-1:8080/` |
| `http://HOST:19081/mock-2/` | `wiremock-2:8080/` |
| `http://HOST:19081/mock-3/` | `wiremock-3:8080/` |
| `http://HOST:19081/mock-4/` | `wiremock-4:8080/` |
| `http://HOST:19081/mock-5/` | `wiremock-5:8080/` |

Nginx strips the selected `/mock-N/` prefix and preserves the remaining path,
query string, method and body. Define stubs against `/demo/empty`, not
`/mock-1/demo/empty`. The same routing supports admin calls, for example
`POST http://HOST:19081/mock-1/__admin/mappings`. Each mock keeps its own mappings.
Direct ports 19001–19005 remain available. A prefix without its trailing slash
redirects with 308; unknown prefixes return 404. Nginx `/healthz` checks the proxy
only; `/mock-N/__admin/health` checks the corresponding WireMock.

The Nginx configuration is embedded in the YAML; no separate file upload or
Docker config/secret is needed. It disables caching, request/response buffering
and upstream retries, uses HTTP/1.1 upstream keepalive, and allows 75-second
upstream read/send inactivity timeouts. Configuration and temporary files use
an ephemeral `/tmp`. Six-second mock responses remain mapping-controlled.

Each service has exactly one replica. Swarm ingress makes all five ports reachable
through a reachable Swarm node; each port routes to its corresponding instance.
Give each instance a distinct node if you want an unshared 4-core CPU budget.
Co-location is allowed but services share that node's actual resources. The five
limits total 20 CPU / 20 GiB; limits do not reserve dedicated capacity.

Retained tuning per instance: `-Xms256m -Xmx3g`, 4 CPU / 4 GiB limit, accept
backlog 4096, 128 container threads, asynchronous responses with 64 threads,
template cache 1000, request journal/logging disabled, gzip and HTTP/2 disabled.
`WIREMOCK_ACCEPT_BACKLOG` optionally overrides 4096 for all five instances.
Container logs are bounded at three 10 MiB files. Services have health checks,
restart-on-failure and stop-first updates. The root filesystem is read-only with
a private 64 MiB `/tmp`. Our capture/metrics extension is not loaded, so the
custom capture and JVM Prometheus endpoint is not present.

No mappings are installed initially. Upload your mappings separately to each
instance at `http://HOST:19001/__admin/mappings` through port 19005. Uploads are
in-memory; reapply after restart or task replacement. Do not request persistent
mapping saves on this read-only deployment. Request journalling is disabled, so
use your client's results for request evidence.

For example, install an empty 200 response with a six-second delay on all five:

```sh
WIREMOCK_HOST=your-swarm-host
for port in 19001 19002 19003 19004 19005; do
  curl --fail-with-body -X POST "http://${WIREMOCK_HOST}:${port}/__admin/mappings" \
    -H 'Content-Type: application/json' \
    --data '{"request":{"method":"POST","urlPath":"/demo/empty"},"response":{"status":200,"fixedDelayMilliseconds":6000}}' || break
done

curl -sS -o /dev/null -w 'status=%{http_code} seconds=%{time_total}\n' \
  -X POST "http://${WIREMOCK_HOST}:19001/demo/empty"
```

Built-in response templating is available by setting
`"transformers":["response-template"]` in a mapping's response; it needs no
additional extension jar. Delay is a mapping setting, not a global server delay.
Use `/__admin/health` on each port for health. Keep these admin endpoints on your
trusted lab network. This setup does not establish a 1,000 requests/s capacity
per instance or across all five.

The same sample mapping can be installed through Nginx:

```sh
curl --fail-with-body -X POST "http://${WIREMOCK_HOST}:19081/mock-1/__admin/mappings" \
  -H 'Content-Type: application/json' \
  --data '{"request":{"method":"POST","urlPath":"/demo/empty"},"response":{"status":200,"fixedDelayMilliseconds":6000}}'

curl -sS -o /dev/null -w 'status=%{http_code} seconds=%{time_total}\n' \
  -X POST "http://${WIREMOCK_HOST}:19081/mock-1/demo/empty"
```

Ordinary Docker Compose can also read this file; export all six node variables
(for example all to your local hostname) before `docker compose -f
deploy/portainer/stack-official-five.yml up -d`. Ordinary Compose runs all five
locally and does not implement Swarm node placement.

Upstream references: [Docker image](https://wiremock.org/docs/standalone/docker/),
[standalone tuning](https://wiremock.org/docs/standalone/java-jar/) and
[Nginx proxy routing](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass).

## Local verification, 9 October 2026

[Verification record](upstream-five-verification.json): both Docker Swarm and
Compose configuration parsing passed, and all 22 Portainer configuration tests
passed. All five upstream WireMocks and Nginx 1.30.5 ran together locally, with
the six published ports restricted to loopback for this test. Each mock started
with zero mappings. Mapping uploads through its `/mock-N/` route succeeded;
empty 200s took 6.008–6.012 seconds, JSON templates worked, headers/query strings
were preserved and mappings remained isolated. A malformed mapping was rejected
without losing service health. Direct-port mapping readback matched proxy readback.
Nginx configuration validation passed; no service restarted or reported OOM.
Containers were stopped after the smoke. This is not an AWS Swarm deployment or
a load-capacity test. The generated stack reproduces exactly from `render.py`.
