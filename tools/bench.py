#!/usr/bin/env python3
"""Portable isolated Compose server + four-engine Swarm Gatling runner. All configuration and verdicts are retained."""

import argparse, hashlib, json, os, platform, shutil, subprocess, sys, threading, time, urllib.request, uuid, signal
from pathlib import Path
from injector import GENERATOR, ARRIVAL_MODEL
from fixtures import DELAYS, SIZES, TEMPLATES, generate
from report import write_summary
from verdict import evaluate
from swarm import SwarmEngines, ENGINE_COUNT

ROOT = Path(__file__).resolve().parents[1]


def call(command, *, env=None, output=None, check=True, timeout=None):
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=output or subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
        timeout=timeout,
    )


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def select_cases(cases, case, delay_ms, sizes=None, templates=None):
    if case != "mixed" and any(v is not None for v in (delay_ms, sizes, templates)):
        raise ValueError("Exact --case cannot combine with delay/size/template filters")
    selected = [
        c
        for c in cases
        if (case == "mixed" or c["id"] == case)
        and (delay_ms is None or c["delay"] == delay_ms)
        and (sizes is None or c["size"] // 1024 in sizes)
        and (templates is None or c["template"] in templates)
    ]
    if not selected:
        raise ValueError("No cases match the explicit selection")
    return selected


def run(args):
    identifier = uuid.uuid4().hex[:16]
    root = ROOT / "results" / identifier
    root.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(
        RUN_NAMESPACE=identifier,
        CAPTURE_ENABLED=str(args.capture == "on").lower(),
        MOCK_PORT=str(args.port),
        METRICS_PORT=str(args.port + 1),
    )
    compose = [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.swarm.yaml",
        "-p",
        "wmb-" + identifier,
        "--profile",
        args.mode,
    ]
    generate(ROOT / "fixtures")
    cases = json.loads((ROOT / "fixtures/cases.json").read_text())
    selected = select_cases(
        cases, args.case, args.delay_ms, args.size_kib, args.template
    )
    (root / "selected-cases.json").write_text(json.dumps(selected, indent=2))
    config = vars(args) | dict(
        runId=identifier,
        arrivalModel=ARRIVAL_MODEL,
        generator=GENERATOR,
        engines=ENGINE_COUNT,
        perEngineOffered=args.offered / ENGINE_COUNT,
        host=platform.uname()._asdict(),
        started=time.time(),
    )
    (root / "config.json").write_text(json.dumps(config, indent=2))
    environment_evidence = {
        "docker": json.loads(
            call(["docker", "version", "--format", "{{json .}}"]).stdout
        ),
        "compose": call(["docker", "compose", "version"]).stdout.strip(),
        "logicalCpus": os.cpu_count(),
    }
    for name in ["cpuinfo", "meminfo"]:
        proc = Path("/proc") / name
        if proc.exists():
            environment_evidence[name] = proc.read_text()
    (root / "environment.json").write_text(json.dumps(environment_evidence, indent=2))
    source_files = [
        ROOT / name
        for name in [
            "Dockerfile",
            "compose.yaml",
            "compose.swarm.yaml",
            "swarm.yaml",
            "pom.xml",
        ]
    ]
    for folder in ["src", "tools", "tests"]:
        source_files.extend(
            p
            for p in (ROOT / folder).rglob("*")
            if p.is_file() and not {"__pycache__", "target"}.intersection(p.parts)
        )
    fingerprint = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source_files)
    }
    (root / "source-sha256.json").write_text(json.dumps(fingerprint, indent=2))
    metrics_url = f"http://127.0.0.1:{args.port+1}/metrics"
    print(
        json.dumps(
            {
                "run": identifier,
                "mode": args.mode,
                "seconds": args.seconds,
                "target": args.target,
                "offered": args.offered,
                "result": str(root),
            }
        ),
        flush=True,
    )
    stop = threading.Event()
    requested_stop = threading.Event()
    fault = []
    previous_signal = signal.signal(signal.SIGINT, lambda *_: requested_stop.set())
    engines = SwarmEngines(root, identifier, environment, call)

    def monitor():
        failures = 0
        next_progress = time.monotonic() + 60
        with (root / "telemetry.jsonl").open("w") as output:
            while not stop.is_set():
                try:
                    snapshot = {
                        "timestamp": time.time(),
                        "metrics": get(metrics_url),
                        "diskFree": shutil.disk_usage(ROOT).free,
                    }
                    snapshot["containers"] = call(
                        [
                            "docker",
                            "stats",
                            "--no-stream",
                            "--format",
                            "{{json .}}",
                            *json.loads((root / "containers.json").read_text()),
                            *engines.container_ids,
                        ],
                        check=False,
                    ).stdout
                    failures = 0
                    output.write(json.dumps(snapshot) + "\n")
                    output.flush()
                    if time.monotonic() >= next_progress:
                        print(
                            json.dumps(
                                {
                                    "progress": identifier,
                                    "timestamp": snapshot["timestamp"],
                                    "metrics": snapshot["metrics"],
                                    "diskFree": snapshot["diskFree"],
                                }
                            ),
                            flush=True,
                        )
                        next_progress = time.monotonic() + 60
                    if snapshot["diskFree"] < 2 * 1024**3:
                        fault.append("Disk below 2GiB reserve")
                        break
                except Exception as error:
                    failures += 1
                    if failures >= 3:
                        fault.append(
                            "Mock metrics unavailable for three consecutive samples"
                        )
                    output.write(
                        json.dumps(
                            {"timestamp": time.time(), "error": type(error).__name__}
                        )
                        + "\n"
                    )
                    output.flush()
                stop.wait(10)

    try:
        environment["BENCH_NETWORK"] = engines.prepare()
        with (root / "deployment.log").open("w") as log:
            call(
                compose + ["up", "-d", "rabbit", "archive", args.mode],
                env=environment,
                output=log,
            )
        deadline = time.monotonic() + 150
        while True:
            try:
                metrics = get(metrics_url)
                if args.capture == "off" or metrics["brokerConnected"]:
                    break
            except Exception:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Mock/capture startup timed out")
            time.sleep(1)
        ids = call(compose + ["ps", "-q"], env=environment).stdout.split()
        (root / "containers.json").write_text(json.dumps(ids))
        (root / "container-inspect-before.json").write_text(
            call(["docker", "inspect", *ids]).stdout
        )
        (root / "mock-runtime.json").write_text(json.dumps(metrics, indent=2))
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        engines.start(args.mode, args.offered, args.warmup, args.seconds)
        deadline = time.monotonic() + args.seconds + args.warmup + 210
        while not engines.complete():
            if requested_stop.is_set():
                window = json.loads((root / "window.json").read_text())
                window["endMs"] = min(window["endMs"], int(time.time() * 1000))
                (root / "window.json").write_text(json.dumps(window))
                engines.graceful_stop()
                deadline = time.monotonic() + 90
                requested_stop.clear()
            if fault or time.monotonic() > deadline:
                raise RuntimeError(fault or "Injector timeout")
            time.sleep(2)
        engines.merge()
        deadline = time.monotonic() + 180
        while args.capture == "on":
            metrics = get(metrics_url)
            if metrics["pending"] == 0:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Outbox failed to drain")
            time.sleep(1)
        # Publisher confirms precede consumer commit: wait until Rabbit delivery is archived too.
        if args.capture == "on":
            import sqlite3

            archive = ROOT / "state" / identifier / "archive/events.db"
            while True:
                try:
                    with sqlite3.connect(f"file:{archive}?mode=ro", uri=True) as db:
                        count = db.execute("SELECT count(*) FROM events").fetchone()[0]
                    if count == metrics["committed"]:
                        break
                except sqlite3.Error:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "Archive failed to reconcile all committed captures"
                    )
                time.sleep(1)
        else:
            archive = None
        stop.set()
        monitor_thread.join(15)
        inspections = json.loads(
            call(["docker", "inspect", *ids, *engines.container_ids]).stdout
        )
        (root / "container-inspect-after.json").write_text(
            json.dumps(inspections, indent=2)
        )
        report = evaluate(
            root, archive, args.target, args.capture == "on", get(metrics_url)
        )
        services_running = all(
            row["State"]["Running"] for row in inspections if row["Id"] in ids
        )
        stable = services_running and all(
            not row["State"]["OOMKilled"] and row["RestartCount"] == 0
            for row in inspections
        )
        report["checks"]["noOomOrRestart"] = stable
        report["checks"]["fourEnginesCompleted"] = (
            len(engines.container_ids) == ENGINE_COUNT
        )
        report["pass"] = all(report["checks"].values())
        (root / "verdict.json").write_text(json.dumps(report, indent=2))
        write_summary(root)
        print(json.dumps(report), flush=True)
        return report["pass"]
    except Exception as error:
        (root / "failure.json").write_text(json.dumps({"error": str(error)}, indent=2))
        raise
    finally:
        stop.set()
        signal.signal(signal.SIGINT, previous_signal)
        with (root / "service.log").open("w") as log:
            call(
                compose + ["logs", "--no-color"],
                env=environment,
                output=log,
                check=False,
            )
        engines.logs_and_stop(args.keep)
        if not args.keep:
            call(compose + ["down"], env=environment, check=False)
        engines.remove_network(args.keep)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["official", "headless"], required=True)
    parser.add_argument("--capture", choices=["on", "off"], required=True)
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--offered", type=int, default=1020)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--case", default="mixed")
    parser.add_argument("--delay-ms", type=int, choices=DELAYS)
    parser.add_argument(
        "--size-kib", type=int, nargs="+", choices=[s // 1024 for s in SIZES]
    )
    parser.add_argument("--template", nargs="+", choices=TEMPLATES)
    parser.add_argument("--port", type=int, default=18880)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    if (
        not 1 <= args.target <= 1000
        or not args.target <= args.offered <= 1200
        or args.seconds < 1
        or args.warmup < 10
    ):
        parser.error("Invalid explicit target/offered/duration/warmup")
    if args.continuous:
        args.seconds = 31536000
    return 0 if run(args) else 1


if __name__ == "__main__":
    sys.exit(main())
