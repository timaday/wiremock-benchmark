#!/usr/bin/env python3
"""Owned broker outage + mock SIGKILL proof, retaining outbox/archive evidence."""
import base64, concurrent.futures, json, os, sqlite3, time, urllib.request, uuid, zlib
from pathlib import Path
from bench import ROOT, call, get
from fixtures import generate, response


def probe(mode):
    identifier = uuid.uuid4().hex[:16]
    out = ROOT / "results" / ("fault-" + identifier)
    out.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        RUN_NAMESPACE=identifier,
        CAPTURE_ENABLED="true",
        MOCK_PORT="18890",
        METRICS_PORT="18891",
    )
    compose = ["docker", "compose", "-p", "wmb-fault-" + identifier, "--profile", mode]
    generate(ROOT / "fixtures")
    report = {"mode": mode, "runId": identifier, "checks": {}}

    def wait(predicate):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception:
                pass
            time.sleep(0.2)
        raise RuntimeError("Fault probe state deadline exceeded")

    try:
        with (out / "deployment.log").open("w") as log:
            call(compose + ["up", "-d", "rabbit", "archive", mode], env=env, output=log)
        wait(lambda: get("http://localhost:18891/metrics")["brokerConnected"])
        call(compose + ["stop", "rabbit"], env=env)

        def send(sequence):
            request_id = identifier + "-" + f"{sequence:012d}"
            # Derive exact request length without a second fixture format contract.
            prefix = '{"id":"' + request_id + '","padding":"'
            body = (prefix + "x" * (1024 - len(prefix) - 2) + '"}').encode()
            req = urllib.request.Request(
                "http://localhost:18890/bench/json-1024-0",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bench-Run": identifier,
                    "X-Bench-Id": request_id,
                },
            )
            with urllib.request.urlopen(req, timeout=30) as result:
                assert result.read().decode() == response("json", 1024, request_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(send, range(40)))
        wait(lambda: get("http://localhost:18891/metrics")["pending"] == 120)
        report["checks"]["brokerOutageRetains120Events"] = True
        mock = call(compose + ["ps", "-q", mode], env=env).stdout.strip()
        call(["docker", "kill", "--signal", "KILL", mock])
        call(["docker", "start", mock])
        wait(lambda: get("http://localhost:18891/metrics")["pending"] == 120)
        report["checks"]["mockKillPreserves120CommittedEvents"] = True
        call(compose + ["start", "rabbit"], env=env)
        wait(lambda: get("http://localhost:18891/metrics")["pending"] == 0)
        archive = ROOT / "state" / identifier / "archive/events.db"

        def reconciled():
            with sqlite3.connect(f"file:{archive}?mode=ro", uri=True) as db:
                return (
                    db.execute(
                        "SELECT count(*) FROM events WHERE run_id=?", (identifier,)
                    ).fetchone()[0]
                    == 120
                )

        wait(reconciled)
        with sqlite3.connect(f"file:{archive}?mode=ro", uri=True) as db:
            phases = dict(
                db.execute(
                    "SELECT phase,count(*) FROM events WHERE run_id=? GROUP BY phase",
                    (identifier,),
                )
            )
            assert phases == {
                "REQUEST": 40,
                "RESPONSE_PREPARED": 40,
                "SEND_COMPLETED": 40,
            }
            actual = {}
            for request_id, phase, payload in db.execute(
                "SELECT request_id,phase,payload_zlib FROM events WHERE run_id=?",
                (identifier,),
            ):
                record = json.loads(zlib.decompress(payload))
                assert (
                    record["requestId"] == request_id
                    and record["runId"] == identifier
                    and record["phase"] == phase
                )
                actual[(request_id, phase)] = base64.b64decode(record["bodyBase64"])
            for sequence in range(40):
                request_id = identifier + "-" + f"{sequence:012d}"
                prefix = '{"id":"' + request_id + '","padding":"'
                assert (
                    actual[(request_id, "REQUEST")]
                    == (prefix + "x" * (1024 - len(prefix) - 2) + '"}').encode()
                )
                assert (
                    actual[(request_id, "RESPONSE_PREPARED")]
                    == response("json", 1024, request_id).encode()
                )
                assert actual[(request_id, "SEND_COMPLETED")] == b""
        report["checks"]["externalArchiveReconcilesEveryPhase"] = True
        report["pass"] = True
    finally:
        (out / "verdict.json").write_text(json.dumps(report, indent=2))
        with (out / "services.log").open("w") as log:
            call(compose + ["logs", "--no-color"], env=env, output=log, check=False)
        call(compose + ["down"], env=env, check=False)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["headless", "official"], required=True)
    probe(parser.parse_args().mode)
