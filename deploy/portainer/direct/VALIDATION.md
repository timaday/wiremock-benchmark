# Direct capture validation — 2026-10-05

Implemented from base commit `8fe8539`. Published public GHCR image tags:

- `ghcr.io/timaday/wiremock-lab-official:20261005-direct-2`
- `ghcr.io/timaday/wiremock-lab-headless:20261005-direct-2`

Both images were built using `direct/build.py`. Official retains its Java 17
runtime; headless retains OpenJDK 27. The Java extension targets Java 17 so both
load the same artifact. Both ran with a read-only root and only 64 MiB tmpfs
scratch, no persistent filesystem mount.

Verified locally with Docker 29.8.1:

- Maven: **24 tests passed**, none skipped when the explicit test RabbitMQ URI was
  supplied. Includes bounded admission, delayed/negative/uncertain confirmation,
  timeouts/shutdown, request validation, existing SQLite commit/reopen checks,
  real classic/quorum persistence flags and redelivery, and mandatory routing.
- **10 Portainer manifest checks** passed with Docker's Swarm parser, including
  required image/broker settings, read-only/tmpfs layout and `on-failure` restart.
- **6 HiveForge generation regression checks** passed.
- **16 bad requests** (eight per runtime) returned 400/413 without changing PID or
  restarting. Unmatched non-benchmark requests returned 404 normally. Rejection
  counters increased; capture error/confirmed counters did not.
- **48 valid HTTP requests** covered all twelve six-second size/template cases
  per runtime, before and after broker recovery. **144 full capture events**
  reconciled against client IDs, phase, exact body length and SHA-256.
- Broker loss caused explicit capture failure; local Docker `on-failure`
  supervision restarted both processes. Both recovered without manual mock
  restart once the broker was restored. No failed request was reported as a
  successful captured response.
- Initial direct-image startup tests also verified nonzero exit with no broker.

The final reproducible command is in [DIRECT-RABBIT.md](../DIRECT-RABBIT.md).
The [retained verification summary](verification.json) includes source evidence
hashes. Raw successful resilience evidence, logs and captures are local artifacts under
[`results/direct-rabbit-resilience-20261005-final`](../../../results/direct-rabbit-resilience-20261005-final/verification.json).
Maven/build logs and initial protocol checks are under
[`results/direct-rabbit-20261005`](../../../results/direct-rabbit-20261005/maven-resilient-test.log).
Earlier failed test attempts are retained: a stale Docker-assigned broker port,
checking before broker readiness, and two harness issues (stderr capture and
temporary absence of a published port during restart). Those are not passing
evidence; the final run corrected the harness checks and completed successfully.

Limits: the recovery supervisor was local Docker; actual remote Swarm scheduling
and Portainer UI deployment were not exercised. The disposable test broker used
tmpfs, so this verifies the protocol, not broker disk/power-loss durability.
No 1,000 requests/s or one-hour qualification is claimed. The existing PocketHive
postprocessor was not exercised; it must support the capture envelope and durable
acknowledgement contract. Both images are published to GHCR. Anonymous access to
the manifest, configuration and every layer was verified; registry digests match
the tested images. See [image-lock.json](image-lock.json).
