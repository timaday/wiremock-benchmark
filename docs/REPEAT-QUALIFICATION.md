# Requested mixed-hour repeat

Status: official-image repeat passed; headless repeat was interrupted and did not qualify.

Same declared workload as the original qualification: four JMeter engines,
255 requests/s offered per engine (1,020/s total), with a 1,000 successful
responses/s target in every full minute. Capture stays enabled. Each runtime
has a separate 60s warmup, 3,600s measured hold, and final drain/reconciliation.

- Equal request/response sizes: 1, 5, 10 and 50 KiB.
- Fixed per-case delays: 0, 1, 1.5, 3, 4, 5 and 6 seconds.
- Two dynamic response patterns: correlated JSON and correlated text.
- Static JSON is a control, giving 84 size/delay/template combinations in total.
- Cases cycle deterministically with equal weighting. This is a mixed hour;
  it does not place every individual case at 1,000 requests/s for an hour.

| Runtime | Successful responses/s | Lowest full minute | HTTP errors | Measured captures | Result |
|---|---:|---:|---:|---:|---|
| Official WireMock 3.13.2 / Java 17 | 1,020.16 | 1,018.17/s | 0 | 11,019,390 / 11,019,390 | Pass |
| Embedded WireMock 3.13.2 / Java 27 | Incomplete | Incomplete | No final verdict | Not reconciled | Interrupted |

Official run: `c0038d8802844d1f`; 3,673,130 measured request starts. Its
delay-adjusted p50/p95/p99 were 25/45/62ms, with a maximum of 159ms.
Headless run: `871eeb32ec094817`.

Source, runtime, resource limits, JTL, telemetry and archives remain retained
under each run's `results/` and `state/` directories. Full coverage counts and
the interrupted headless evidence is retained without a pass claim.

The [contract](CONTRACT.md) defines the gates and durability boundaries. The
[original qualification](QUALIFICATION.md) records resource caps, compressible
fixture padding, uncompressed HTTP bodies, and platform/comparison limits;
those limits also apply here. The same authorised PocketHive test stack is
restored and verified (19 running, health checks healthy, HTTP 200 on port 18089)
on 2026-09-27 after recovery. The headless repeat stopped around 30 minutes;
its supervisor was gone and all four tasks had failed. It requires a new full run.
