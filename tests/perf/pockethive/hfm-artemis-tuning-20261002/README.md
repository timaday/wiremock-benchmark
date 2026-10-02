# Artemis tuning trials — 2 October 2026

Run fresh headless smoke, then three bounded diagnostic trials against the existing HFM server: baseline 1 MiB consumer window, 256 KiB consumer window, and 4 MiB consumer window. Change only one tuning dimension per trial.

Each diagnostic offers four 255/s lanes, six-second responses, 1/5/10/50 KiB payloads and static/JSON/text templates. It has 60 seconds warm-up, 180 measured seconds and 30 final arrival seconds: 275,400 requests and 826,200 capture events. Smoke expects 48 requests and 144 events. Redis evidence, persistent messages, HTTP settings, JVMs and backlog 4096 stay unchanged.

Select ARTEMIS explicitly on the Orchestrator. Retain the explicit `tcp://artemis:61616` endpoint; the topology owner passes that connection to workers. The deployed typed connection contract rejects URI query parameters, so large-message threshold tuning is not included. Do not override provisioned connection settings in bee environment variables. Consumer windows belong in bundle input configuration.

Keep scoped request-address BLOCK limits at 128 MiB each, the results limit at 256 MiB and global broker limit at 1 GiB. Do not disable persistence, use unbounded consumer windows, increase address capacity to hide backpressure or weaken the original integrity/rate gates. No new trial starts until the previous trial and capture have drained and their evidence is retained.

Read run-plan.json for exact IDs, settings and paths. Validate and publish committed bundles through PocketHive MCP. Record actual worker images and resolved configuration. Use the existing canonical analyze.py and stage_timing.py, plus broker queue/large-message statistics, memory, disk and TCP watchers. Capture-off and broker-only probes are not qualification results.

Select a candidate after diagnostic integrity and rate checks; then prepare a fresh hour bundle and repeat the unchanged 3,600-second, every-minute gate. The old RabbitMQ pass remains the comparison reference. Resolve RAM and storage prerequisites first. Results and large archives remain outside Git.
