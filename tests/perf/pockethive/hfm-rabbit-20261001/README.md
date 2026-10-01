# RabbitMQ headless comparison, 1 October 2026

Fresh smoke, full-rate short and one-hour workloads for the existing HFM headless server at backlog 4096. The hour repeats run `63a628ffd1d177e1` with six-second delay, 1/5/10/50 KiB bodies, three templates, four 255/s lanes and unchanged processor/evidence settings.

Select `POCKETHIVE_WORK_TYPE=RABBITMQ` on the existing local Orchestrator before creating these swarms. The generated bundles explicitly select RabbitMQ on all 13 Work input/output boundaries. Rabbit input uses prefetch 50, one consumer, nonexclusive; output uses persistent messages with publisher confirms disabled, matching the adapter defaults explicitly. Rabbit prefetch is message-count based and is not equivalent to Artemis's byte-based 1 MiB consumer window. Record that transport tuning difference when comparing.

Use PocketHive's RabbitMQ for Work traffic. HFM's RabbitMQ remains the separate WireMock capture broker; Redis remains the result sink. Do not change HTTP rate, concurrency, timeout, payload or capture configuration between transport runs.

Before the hour: smoke must reconcile all 48 results and 144 capture events; short load must reconcile all 91,800 results and 275,400 capture events. Record rate failures honestly. The hour requires all 3,763,800 responses and 11,291,400 capture events to reconcile, valid collected throughput of at least 1,000/s and every measured minute at the same target. Apply the existing canonical verifier; do not redefine pass thresholds.

Record RabbitMQ memory/disk alarms, ready and unacknowledged queue depth/bytes, worker health, host/guest memory and disk, and HFM TCP counters. Stop before resource exhaustion; no queue TTL, drop-head overflow or message deletion is part of this test. Persistent RabbitMQ disk writes are expected and are not the Artemis paging policy.

Preparation and exact identity/hash evidence are in `preparation.json`. Results belong under ignored `results/pockethive-hfm-rabbit-20261001`, with large archives in a dedicated evidence volume. HFM storage capacity must be resolved before starting the hour.
