#!/usr/bin/env python3
"""Sequential fixed-delay qualification. Default: print plan; --execute runs it."""
import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fixtures import DELAYS, SIZES, TEMPLATES
from report import write_summary

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
MODES = ("official", "headless")


def schedule(delays=DELAYS):
    return [dict(mode=mode, delayMs=delay) for delay in delays for mode in MODES]


def required_bytes(count):
    return (12 * count + 10) * GIB


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def completed(attempt):
    if attempt.get("state") != "passed":
        return False
    path = ROOT / "results" / attempt["runId"] / "verdict.json"
    verdict = json.loads(path.read_text())
    return verdict["pass"] and verdict["measuredSeconds"] == 3600


def remaining(state):
    done = {(a["mode"], a["delayMs"]) for a in state["attempts"] if completed(a)}
    return [r for r in state["schedule"] if (r["mode"], r["delayMs"]) not in done]


def summarize(run_id):
    root = ROOT / "results" / run_id
    summary = write_summary(root)
    verdict = summary["verdict"]
    heap = summary["heapUsedBytes"]
    return dict(
        completedRps=verdict["completedRps"],
        minimumMinuteRps=min(m["completedRps"] for m in verdict["minutes"]),
        errors=verdict["errors"],
        measuredSeconds=verdict["measuredSeconds"],
        sampledHeapMinBytes=heap["min"] if heap else None,
        sampledHeapMaxBytes=heap["max"] if heap else None,
        java=summary["java"],
        resources=summary["resources"],
    )


def report(directory, state):
    save(directory / "status.json", state)
    lines = [
        "# Fixed-delay qualification",
        "",
        f"State: {state['state']}",
        "",
        f"Workload: {state['workload']}",
        "",
        "Each run: 3,600 measured seconds; 60s warmup; four engines; target 1,000/s; offered 1,020/s.",
        "",
        "| Runtime | Delay (s) | State | RPS | Min minute RPS | Errors | Evidence |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for attempt in state["attempts"]:
        summary = attempt.get("summary", {})
        run_id = attempt.get("runId")
        evidence = (
            f"[results](../../results/{run_id}) / [capture and mock GC](../../state/{run_id})"
            if run_id
            else "See attempt log"
        )
        lines.append(
            f"| {attempt['mode']} | {attempt['delayMs']/1000:g} | {attempt['state']} | "
            f"{summary.get('completedRps', '—')} | {summary.get('minimumMinuteRps', '—')} | "
            f"{summary.get('errors', '—')} | {evidence} |"
        )
    lines += [
        "",
        "Per run: verdict.json (minute rates, latency, capture gates), telemetry.jsonl (CPU/container memory and mock heap), mock-runtime.json (JVM), engine-*-gc.log, state/<id>/outbox/gc.log, and full durable archives.",
        "",
        "Sampled heap is not a heap dump or a memory-leak verdict. Failed/interrupted attempts are retained.",
    ]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n")


def command(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, **kwargs)


def run_suite(args, directory, state):
    pending = remaining(state)
    workload = state["workload"]
    if args.max_runs:
        pending = pending[: args.max_runs]
    free = shutil.disk_usage(ROOT).free
    needed = required_bytes(len(pending))
    print(
        json.dumps(
            dict(
                runs=pending,
                workload=workload,
                measuredHours=len(pending),
                freeGiB=round(free / GIB, 1),
                requiredGiB=needed / GIB,
            )
        ),
        flush=True,
    )
    if not args.execute or not pending:
        return 0
    if free < needed:
        raise RuntimeError(
            f"Need {needed/GIB:g} GiB free; have {free/GIB:.1f}. Use a larger filesystem or explicit --max-runs batch. No data deleted."
        )
    busy = command(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True
    ).stdout
    if any(name.startswith("wmb-") for name in busy.splitlines()):
        raise RuntimeError(
            "Another benchmark container is running; wait for it to finish"
        )
    child = None
    stopping = False
    paused = []

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)

    previous = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    state["state"] = "running"
    report(directory, state)
    try:
        # Build before pausing application services. No benchmark load overlaps build.
        with (directory / "build.log").open("a") as output:
            command(
                [sys.executable, "tools/fixtures.py"],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            command(
                ["docker", "compose", "--profile", "tools", "build", "jmeter"],
                env=os.environ | {"RUN_NAMESPACE": "build", "CAPTURE_ENABLED": "true"},
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        if stopping:
            raise InterruptedError("Stopped before tests")
        if args.pause_project:
            compose = [
                "docker",
                "compose",
                "-p",
                args.pause_project,
                "-f",
                str(Path(args.pause_file).resolve()),
            ]
            paused = command(
                compose + ["ps", "--status", "running", "-q"], capture_output=True
            ).stdout.split()
            state["restoreContainerIds"] = paused
            state["restoration"] = "pending"
            report(directory, state)
            if paused:
                command(["docker", "stop", *paused], stdout=subprocess.DEVNULL)
        for index, item in enumerate(pending):
            if stopping:
                raise InterruptedError("Suite interrupted")
            if shutil.disk_usage(ROOT).free < required_bytes(len(pending) - index):
                raise RuntimeError(
                    "Insufficient disk for remaining batch; evidence retained"
                )
            attempt = item | dict(state="running", started=time.time())
            state["attempts"].append(attempt)
            log_path = directory / f"attempt-{len(state['attempts']):02d}.log"
            attempt["log"] = str(log_path.relative_to(ROOT))
            report(directory, state)
            with log_path.open("w") as output:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        "tools/bench.py",
                        "--mode",
                        item["mode"],
                        "--capture",
                        "on",
                        "--delay-ms",
                        str(item["delayMs"]),
                        "--seconds",
                        "3600",
                        "--warmup",
                        "60",
                        "--target",
                        "1000",
                        "--offered",
                        "1020",
                        "--size-kib",
                        *map(str, workload["sizeKiB"]),
                        "--template",
                        *workload["templates"],
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in child.stdout:
                    output.write(line)
                    output.flush()
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "run" in event:
                        attempt["runId"] = event["run"]
                        report(directory, state)
                        print(json.dumps(attempt), flush=True)
                code = child.wait()
                child = None
            attempt.update(
                exitCode=code,
                ended=time.time(),
                state="interrupted" if stopping else "failed",
            )
            if not stopping and code == 0 and "runId" in attempt:
                attempt["state"] = "passed"
                if not completed(attempt):
                    attempt["state"] = "failed"
                attempt["summary"] = summarize(attempt["runId"])
            report(directory, state)
            if attempt["state"] != "passed":
                raise RuntimeError(
                    "Run failed/interrupted; stopped sequence. See attempt log."
                )
            print(json.dumps(attempt), flush=True)
        state["state"] = "complete" if not remaining(state) else "batch-complete"
        return 0
    except BaseException as error:
        state.update(state="interrupted" if stopping else "failed", error=str(error))
        raise
    finally:
        try:
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.wait()  # Let the owned benchmark drain and clean up before restoration.
            if paused:
                with (directory / "restore.log").open("a") as output:
                    command(
                        ["docker", "start", *paused],
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                state["restoration"] = "started"
            elif args.pause_project:
                state["restoration"] = "nothing-to-restore"
        except BaseException as error:
            state.update(state="failed", restoration="failed", restoreError=str(error))
            raise
        finally:
            report(directory, state)
            for s, handler in previous.items():
                signal.signal(s, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--delay-ms",
        type=int,
        nargs="+",
        choices=DELAYS,
        help="Explicit subset in execution order; default all delays",
    )
    parser.add_argument(
        "--size-kib", type=int, nargs="+", choices=[s // 1024 for s in SIZES]
    )
    parser.add_argument("--template", nargs="+", choices=TEMPLATES)
    parser.add_argument(
        "--resume", type=Path, help="Existing suite directory under results/"
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        help="Explicit batch limit; does not change the full schedule",
    )
    parser.add_argument("--pause-project")
    parser.add_argument("--pause-file")
    args = parser.parse_args()
    if args.resume and any(
        v is not None for v in (args.delay_ms, args.size_kib, args.template)
    ):
        parser.error("Resume uses the saved schedule; omit --delay-ms")
    if bool(args.pause_project) != bool(args.pause_file):
        parser.error("--pause-project and --pause-file are required together")
    if args.max_runs is not None and args.max_runs < 1:
        parser.error("--max-runs must be positive")
    directory = (
        args.resume.resolve()
        if args.resume
        else ROOT
        / "results"
        / ("suite-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    if directory.parent != ROOT / "results":
        parser.error(
            "Suite directory must be directly under this repository's results/"
        )
    state = (
        json.loads((directory / "status.json").read_text())
        if args.resume
        else dict(
            state="planned",
            attempts=[],
            workload=dict(
                sizeKiB=(
                    args.size_kib
                    if args.size_kib is not None
                    else [s // 1024 for s in SIZES]
                ),
                templates=args.template if args.template is not None else TEMPLATES,
            ),
            schedule=schedule(args.delay_ms if args.delay_ms is not None else DELAYS),
        )
    )
    if "workload" not in state:
        parser.error(
            "Saved suite predates explicit workload selection; retain it and start a new suite"
        )
    if not args.execute:
        return run_suite(args, directory, state)
    directory.mkdir(parents=True, exist_ok=True)
    with (ROOT / "results" / ".qualification.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(f"Suite: {directory}", flush=True)
        return run_suite(args, directory, state)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Qualification stopped: {error}", file=sys.stderr)
        sys.exit(1)
