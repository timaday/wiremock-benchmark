# Build record

Authority: the user requested a new portable WireMock benchmark repository,
lossless durable buffering during broker outages, and qualification on this host.
The isolated `ph-release-manual-20260925` stack may be stopped for qualification
and must be restored afterward. Existing PocketHive source is out of scope.

## Intent and steps

1. **Implemented; demonstrated:** identical capture extension in official
   WireMock 3.13.2 and embedded OpenJDK 27 runtimes; actual HTTP exchanges archived
   through RabbitMQ. Local SQLite commits protect capture before hook return.
2. **Demonstrated at small scale:** broker outage and forced process restart
   preserve committed events. Identity/body reconciliation is the oracle.
3. **Proved:** four-engine hooks-off baselines and one-hour capture-on holds pass
   for both runtimes, including every-minute and full-body reconciliation gates.
4. **Proved:** continuous stop/drain path. Final evidence is in
   [QUALIFICATION.md](QUALIFICATION.md). All 19 paused PocketHive containers
   are restored; configured health checks pass and port 18089 returns HTTP 200.
   Owned benchmark services/overlays are removed. No push/remote/commit.

The canonical [contract](CONTRACT.md) owns acceptance criteria. Optional MockServer
comparison is later work. Portable recipes are not cross-platform qualification.

## Decisions and learning

- **Assumed and disclosed:** sizes are KiB, equal request/response body sizes;
  three templates and seven fixed delays cover 84 combinations. Deterministic
  padding is compressible, and HTTP compression is explicitly disabled.
- **Observed:** official-image 100/s and small headless capture runs complete with
  exact bodies and reconciled captures. These are not 1,000/s evidence.
- **Observed:** Constant Throughput Timer millisecond rounding substantially
  reduces a 105/s stimulus to around 100/s. Open Model Thread Group fixed pacing but exhausted ephemeral ports at 1,000/s
  because each iteration opens a connection. Retained both failed experiments;
  the next bounded experiment uses reusable threads and Precise Throughput Timer.
- **Supported:** durability cannot provide zero synchronous overhead. The target
  concerns successful throughput despite commit cost, not zero latency penalty.
- **Bounded:** server completion callbacks do not prove client receipt; JMeter
  verifies receipt. A crash before the request hook commits remains outside the
  durable acceptance boundary. Finite disk cannot buffer an unlimited outage.
- **Comparison boundary:** the portable runner containerises both modes. Headless
  uses embedded WireMock/OpenJDK 27; official retains its supplied JVM. It does not
  isolate the effect of Docker overhead. A direct native launch is documented.

Raw failures and successes remain under `results/` and durable data under `state/`;
these directories are ignored by Git. Per-run source hashes and container/image
inspection identify the actual implementation and runtime used.

- **Observed:** the mixed 1,000/s two-minute hook-off and hook-on checks pass.
  The maximum 50 KiB/6s case exhausted the 1.5 GiB injector heap. Increase the
  declared envelope to a 3 GiB injector heap/5 GiB container and 2 GiB mock
  heap/3 GiB container; repeat comparable runs under those caps. JVM OOM must
  terminate immediately. This is a resource change, not a lower workload target.

- **User steering:** execute four engines in Docker Swarm, splitting the total
  offered rate. Swarm was initially inactive; a local loopback manager was
  initialised. Each run owns and removes its tasks and overlay. The manager
  remains available for repeat runs. Both compressed-capture recovery probes pass.
- **Injector integration learning:** legacy stack interpolation mishandled a
  hyphen inside a required-variable error message. Use explicit environment
  bindings and verify the deployed values. Place the common launch barrier
  before JMeter starts; waiting inside setUp makes its timer catch up old arrivals.

- **Observed, four-engine maximum case:** the official WireMock JVM exhausts
  a 2 GiB heap with 50 KiB bodies and six-second responses. It exits explicitly
  and the run fails. Increase the mock envelope to 3 GiB heap/4 GiB container;
  preserve offered rate, delays, payload sizes and correctness gates.

- **Pacing decision:** precise-timer replay of overdue arrivals prolonged startup
  bursts after injector stalls. Switch to standard Constant Throughput Timer mode
  2: its interval is calculated per client from group size, avoiding the shared
  timer's millisecond ceiling; late clients reset their next interval instead of
  retaining a global arrival backlog. Use 20s thread ramp-up and retain strict
  measured rate/error gates. This is checked against JMeter 5.6.3 source.

- **Proved, official maximum case:** four Swarm engines, 50 KiB request and
  response, fixed 6s delay, capture enabled. Run `f5a87f8174da41a1` passed a
  120s measured window at 1,015.25 successful responses/s, zero errors, and
  366,429/366,429 reconciled capture events. Both measured minutes exceeded
  1,000 responses/s. This is a short capacity result, not an hour-long pass.
  Final envelope: mock 3 GiB heap/4 GiB container; each engine 1 GiB heap/
  1.75 GiB container. Warmup is 60s, including a 20s thread ramp.

- **Proved, headless maximum case:** `7494caba23f54fcd` passed the same 120s
  workload on OpenJDK 27: 1,017.07 successful responses/s, zero errors, and
  368,505/368,505 captures reconciled.
- **Injector sizing correction:** the mixed hooks-off experiment
  `5d2fe3a5bfe84778` failed at 868.14 responses/s despite zero HTTP errors.
  A mean-delay thread budget is insufficient for individually paced clients
  cycling through six-second cases. Automatic sizing now uses the maximum
  selected delay; a regression test guards that concurrency requirement.

- **Proved, official one-hour hold:** `e1a567c274974dee` passed all gates:
  1,020.14 successful responses/s; every minute at least 1,017.7/s;
  zero HTTP errors; all 11,019,456 measured capture events reconciled.
  Full archive reconciliation takes several minutes after traffic stops.
  The four-engine mixed hooks-off baselines pass for both runtimes.

- **Proved, headless one-hour hold:** `64a961b1b97f454f` passed all gates:
  1,020.14 successful responses/s; every minute at least 1,018/s;
  zero HTTP errors; all 11,019,303 measured capture events reconciled.
- **Proved, continuous stop:** `9bac1d0245ef4a59` ran until SIGINT, drained
  all four engines, and passed at 104.30 responses/s against a 100/s target.
  All 28,641 measured captures reconciled. This lower-rate stop check began
  after headless traffic ended, while its offline reconciliation was running.
- **Closeout fix:** Docker service-log export hung after the headless verdict.
  Terminating the owned diagnostic reader allowed cleanup. The final runner
  bounds this optional export to 30s, records/reports incomplete diagnostics,
  and still removes the owned stack. The timeout and cleanup tests pass;
  workload and verdict logic are unchanged. Final local total: 14 Python tests
  plus the four Java tests from the image build, with formatting/config checks.
- **Restored:** `ph-release-manual-20260925`, 19 containers running, all declared
  health checks passing, HTTP 200 on port 18089. Evidence:
  [pockethive-restoration.json](evidence/pockethive-restoration.json).

## Requested repeat of the mixed hour

The user requested another one-hour run with mixed 1/5/10/50 KiB payloads,
0–6s delays and multiple dynamic templates. Repeat the existing 84-case matrix
for both runtimes, sequentially, with four engines and capture enabled.
Official repeat started as `c0038d8802844d1f`. The same authorised PocketHive
stack is paused, with restoration in the supervisor's finalisation step.
Retain the original qualification evidence and add per-case coverage counts
for the repeats. A started or partially observed hour is not a passing verdict.

## 2026-09-27: fixed-delay automation and priority six-second batch

- Mixed repeat `c0038d8802844d1f` passed; `871eeb32ec094817` was interrupted
  without a verdict. Preserved its task failures, raw data and archive. Recovered
  the previously paused PocketHive stack: all 19 running/healthy, UI HTTP 200.
- Added the missing 2s fixtures and `bench.py --delay-ms`. Python selects one
  catalogue written into results; JMeter consumes that exact selection.
- Added sequential `tools/qualify.py`: explicit fixed-delay schedule/subsets,
  disk admission, retained attempts, full-hour-only resume, status/report,
  stop-on-failure and restoration of exactly the authorized paused containers.
- Python checks: 18 passed. Injector rebuilt. User chose smaller batches on this
  disk and prioritized six seconds. Suite `suite-20260927T125702Z` runs official
  then headless at six seconds (one measured hour each), capture on, target1000,
  offered1020, mixed sizes and templates. Running is not a qualification verdict.
- Supervisor log: `.runtime/six-second-qualification.log`; PID record:
  `.runtime/six-second-supervisor.json`. Per-run JVM/CPU/memory/heap/GC evidence
  and durable archives remain under results and state. Full16hours are deferred
  to further explicit storage-admitted batches; no prior evidence is deleted.

## Portable workload/report increment

User requested portable 0–6s, official/headless, varied or fixed payloads, and
memory/heap/JVM/overhead tracking. Kept the proven runtime/extension unchanged.

- Added composable size/template filters to bench and fixed-delay qualification.
  One selected catalogue still owns JMeter assertions and concurrency selection.
- Added measured-window CPU/memory/heap summaries and matched capture/runtime
  comparisons. Negative gates reject inconsistent configurations and failed runs;
  unavailable samples stay unavailable. No performance gates were weakened.
- Documented Linux/WSL2 setup; no user-specific paths or PocketHive dependency.
  macOS/ARM portability remains unqualified; native Windows Python unsupported.
- Self-review: scope delivers controls and evidence; reporting stays outside the
  runtime; risk checks cover window exclusion, missing/partial telemetry, unit
  conversions, inconsistent workloads/resources/JVMs, and failed baselines.
- Unit verification: 28 tests passed; Python compilation and Black checks passed.
  Integration verification IDs/results will be recorded below on completion.

Integration verification completed: all four 60s measured smoke runs passed at
10/s target, 12/s offered, fixed10KiB, zero delay, dynamic JSON/text. Official
capture off/on: `e2fc2f5011cb4432` / `ed8a560cdcdd4ca0`; headless off/on:
`7f15f875ae584d0b` / `df3ce08602b84c13`. Each completed720 measured requests with
zero HTTP errors. Each capture-on run reconciled2160/2160 events. Both capture
overhead comparisons and the official/headless comparison generated successfully.
Evidence: [portable-controls.json](evidence/portable-controls.json). This is
functional verification, not a replacement for the earlier1,000/s hour proofs.
No application/runtime changes, commits, pushes or evidence deletions were made.

## 2026-09-29: replace the maintained JMeter injector with Gatling

Authority: the user selected this repository for the migration and explicitly
requested a push. PocketHive source and its repository-specific Git rules are
out of scope. No global Codex configuration was changed. Checks below are local
development proof, not governed HiveGate execution.

- Replaced the JMX/Groovy plan and image with Gatling 3.15.1/Java 21. Native open
  arrivals, one request per user and shared connections replace client threads.
  Preserved four Swarm engines, quotas, catalogue selection, exact body/delay
  checks, request IDs, actual-byte capture reconciliation and minute gates.
- Added completion counters so missing client results cannot pass. Continuous
  stop closes admission, drains HTTP requests and closes evidence before exit.
- Removed `--threads`; results use per-engine CSV plus native Gatling logs.
  Generator identity comes from the pinned POM. Suite resume rejects historical
  generators; matched comparisons require identical generator/arrival model.
- Source review found the legacy AHC retry setting is ignored by this Gatling
  client. Consumable request streams prevent replay of a consumed POST after a
  pooled connection closes. The maintained fault probe verifies actual server
  counts and IDs, not just logical Gatling samples.
- Checks: 30 Python tests, five injector Java tests in the Docker build, Python
  formatting/compilation, shell syntax, Compose/Swarm rendering and diff checks.
  Fault probe `4af8831e316c4ccf`: eight admitted/completed failed samples, nonzero
  exit, exact corrupt/empty-response hashes, eight distinct server requests.
- Final-image headless continuous run `96b3489cf6644047`: Ctrl+C after 66.195
  measured seconds, 796 measured requests, zero errors, 2,388/2,388 capture
  events, all 916 admitted requests (including warmup) drained across four engines.
  Workload: all sizes/templates at six seconds, target10/s, offered12/s.

Validation runs use an isolated copy under `/tmp` because the repository's
filesystem is below its 2 GiB reserve. Existing evidence and other application
stacks were preserved. Historical JMeter hour-long qualifications remain labeled
as JMeter evidence; these migration checks do not establish a new one-hour hold.

Final-image official capacity run `b5417d23f3e64bb2` passed: 60 measured seconds,
20s warmup, target1,000/s, offered1,020/s, six-second delay, all sizes/templates,
capture on. Measured61,200 requests, completed1,019.65/s, zero errors,
p99=6,079ms (79ms excluding delay), 183,600/183,600 capture records reconciled.
All engines completed without OOM/restart. Owned containers and networks were
removed. Compact configurations, verdicts, counters, source hashes, image IDs
and resource summaries: [gatling-migration.json](evidence/gatling-migration.json).
