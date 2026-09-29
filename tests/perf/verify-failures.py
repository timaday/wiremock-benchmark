#!/usr/bin/env python3
"""Docker integration proof: corrupt bodies and closed connections must fail without replay.

Uses only owned containers/network and retains evidence in results/<run-id>.
Build the official and gatling images first; no capture infrastructure is needed.
"""

import csv, hashlib, json, pathlib, subprocess, time, urllib.request, uuid

root = pathlib.Path(__file__).resolve().parents[2]
identifier = uuid.uuid4().hex[:16]
results = pathlib.Path(root) / "results" / identifier
results.mkdir(parents=True)
fixtures = results / "negative-fixtures"
fixtures.mkdir()
cases = [
    dict(id="static-1024-0", size=1024, delay=0, template="static", example="x" * 1024),
    dict(
        id="text-1024-0",
        size=1024,
        delay=0,
        template="text",
        example="0" * 29 + "x" * 995,
    ),
]
(results / "selected-cases.json").write_text(json.dumps(cases))
for case, response in zip(
    cases, [dict(status=200, body="corrupt"), dict(fault="EMPTY_RESPONSE")]
):
    (fixtures / (case["id"] + ".json")).write_text(
        json.dumps(
            dict(
                request=dict(method="POST", url="/bench/" + case["id"]),
                response=response,
            )
        )
    )
name = "wmb-gatling-negative-" + identifier
mock = name + "-mock"
engine = name + "-engine"


def call(args, **kw):
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kw,
    )


try:
    call(["docker", "network", "create", name])
    call(
        [
            "docker",
            "run",
            "-d",
            "--name",
            mock,
            "--network",
            name,
            "--cpus",
            "1",
            "--memory",
            "512m",
            "-e",
            "JAVA_OPTS=-Xmx256m",
            "-v",
            str(fixtures) + ":/home/wiremock/mappings:ro",
            "-p",
            "127.0.0.1::8080",
            "wiremock-benchmark-official:local",
            "--disable-request-logging",
        ]
    )
    port = json.loads(call(["docker", "inspect", mock]).stdout)[0]["NetworkSettings"][
        "Ports"
    ]["8080/tcp"][0]["HostPort"]
    deadline = time.monotonic() + 40
    while True:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:" + port + "/__admin/mappings", timeout=1
            ) as r:
                assert len(json.load(r)["mappings"]) == 2
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    start = int(time.time() * 1000) + 15000
    cmd = [
        "docker",
        "run",
        "--name",
        engine,
        "--network",
        name,
        "--cpus",
        "1",
        "--memory",
        "768m",
        "-v",
        str(results.parent) + ":/results",
    ]
    for key, value in dict(
        RUN_ID=identifier,
        ENGINE_SLOT=1,
        ENGINE_RATE=4,
        LOAD_START_MS=start,
        MEASURE_END_MS=start + 2000,
        BENCH_HOST=mock,
        HEAP="-Xms128m -Xmx512m",
    ).items():
        cmd += ["-e", f"{key}={value}"]
    result = subprocess.run(
        cmd + ["wiremock-benchmark-gatling:local"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=75,
    )
    (results / "docker.log").write_text(result.stdout)
    rows = list(csv.DictReader((results / "engine-1.csv").open()))
    completion = json.loads((results / "engine-1-completion.json").read_text())
    assert result.returncode != 0, result
    assert len(rows) > 0 and all(r["success"] == "false" for r in rows), rows
    assert completion == dict(started=len(rows), completed=len(rows)), completion
    with urllib.request.urlopen(
        "http://127.0.0.1:" + port + "/__admin/requests", timeout=5
    ) as response:
        received = json.load(response)["requests"]
    assert len(received) == len(rows), "HTTP request was replayed"
    assert len({r["request"]["headers"]["X-Bench-Id"] for r in received}) == len(rows)
    expected = {
        "static-1024-0": hashlib.sha256(b"corrupt").hexdigest(),
        "text-1024-0": hashlib.sha256(b"").hexdigest(),
    }
    assert {r["case_id"] for r in rows} == set(expected)
    assert all(r["response_sha256"] == expected[r["case_id"]] for r in rows)
    summary = dict(
        runId=identifier,
        exitCode=result.returncode,
        requests=len(rows),
        completion=completion,
        allFailed=True,
        actualResponseHashesVerified=True,
        noReplayVerified=True,
    )
    (results / "negative-verdict.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
finally:
    for container in [engine, mock]:
        subprocess.run(
            ["docker", "rm", "-f", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        ["docker", "network", "rm", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
