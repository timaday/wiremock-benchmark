#!/usr/bin/env python3
"""Summarize measured resources or compare two explicitly matched benchmark runs."""
import argparse
import json
import re
import statistics
from pathlib import Path


def read(root, name):
    return json.loads((root / name).read_text())


def stats(values):
    return (
        {
            "samples": len(values),
            "min": min(values),
            "mean": statistics.mean(values),
            "max": max(values),
        }
        if values
        else None
    )


def memory_bytes(text):
    match = re.fullmatch(r"([\d.]+)\s*(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)", text.strip())
    if not match:
        raise ValueError("Unknown Docker memory unit: " + text)
    units = {
        "B": 1,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }
    return float(match[1]) * units[match[2]]


def role(container, mode):
    labels = container["Config"]["Labels"]
    if "com.docker.swarm.service.name" in labels:
        return "engines"
    service = labels["com.docker.compose.service"]
    return "mock" if service == mode else service


def summarize(root):
    root = Path(root).resolve()
    config = read(root, "config.json")
    verdict = read(root, "verdict.json")
    window = read(root, "window.json")
    containers = read(root, "container-inspect-after.json")
    names = {c["Name"].lstrip("/"): role(c, config["mode"]) for c in containers}
    grouped = {r: {"cpu": [], "memory": []} for r in set(names.values())}
    grouped["total"] = {"cpu": [], "memory": []}
    heap = []
    errors = 0
    expected_counts = {r: list(names.values()).count(r) for r in set(names.values())}
    with (root / "telemetry.jsonl").open() as source:
        for line in source:
            row = json.loads(line)
            if not window["startMs"] <= row["timestamp"] * 1000 < window["endMs"]:
                continue
            if "error" in row:
                errors += 1
                continue
            heap.append(row["metrics"]["heapUsed"])
            per_role = {r: [] for r in expected_counts}
            for raw in row["containers"].splitlines():
                item = json.loads(raw)
                r = names[item["Name"]]
                per_role[r].append(
                    (
                        float(item["CPUPerc"].removesuffix("%")),
                        memory_bytes(item["MemUsage"].split("/")[0]),
                    )
                )
            complete = True
            total_cpu = total_memory = 0
            for r, measurements in per_role.items():
                if len(measurements) != expected_counts[r]:
                    complete = False
                    continue
                cpu = sum(m[0] for m in measurements)
                memory = sum(m[1] for m in measurements)
                grouped[r]["cpu"].append(cpu)
                grouped[r]["memory"].append(memory)
                total_cpu += cpu
                total_memory += memory
            if complete:
                grouped["total"]["cpu"].append(total_cpu)
                grouped["total"]["memory"].append(total_memory)
    mock = next(c for c in containers if role(c, config["mode"]) == "mock")
    return dict(
        runId=config["runId"],
        mode=config["mode"],
        capture=config["capture"],
        verdict=verdict,
        workload=read(root, "selected-cases.json"),
        java=read(root, "mock-runtime.json")["java"],
        jvmEnvironment=[
            v
            for v in mock["Config"]["Env"]
            if v.startswith(("JAVA_TOOL_OPTIONS=", "JDK_JAVA_OPTIONS=", "JAVA_OPTS="))
        ],
        heapUsedBytes=stats(heap),
        telemetryErrors=errors,
        resources={
            r: dict(cpuPercent=stats(v["cpu"]), memoryBytes=stats(v["memory"]))
            for r, v in grouped.items()
        },
        evidence=dict(
            telemetry="telemetry.jsonl",
            jvm="mock-runtime.json",
            engineGc="engine-*-gc.log",
            mockGc=f"../../state/{config['runId']}/outbox/gc.log",
            verdict="verdict.json",
        ),
        limitations=[
            "Point-sampled arithmetic means; 100% CPU equals one core.",
            "Heap samples are not retained-heap/leak analysis; GC logs include warmup.",
            "Body padding is compressible; HTTP is uncompressed.",
        ],
    )


def write_summary(root):
    root = Path(root)
    summary = summarize(root)
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    verdict = summary["verdict"]
    workload = summary["workload"]
    heap = summary["heapUsedBytes"]
    lines = [
        "# Benchmark run",
        "",
        f"Runtime: {summary['mode']}; capture: {summary['capture']}; JVM: {summary['java']}.",
        "",
        f"Verdict: {'PASS' if verdict['pass'] else 'FAIL'}; measured {verdict['measuredSeconds']:g}s; completed {verdict['completedRps']:.2f}/s; errors {verdict['errors']}.",
        "",
        f"Delays (ms): {sorted({c['delay'] for c in workload})}; payloads (KiB): {sorted({c['size']//1024 for c in workload})}; templates: {sorted({c['template'] for c in workload})}.",
        "",
        f"Latency p95: {verdict['latencyMs']['p95']}ms; excluding configured delay: {verdict['delayAdjustedLatencyMs']['p95']}ms.",
        "",
        "| Component | Mean CPU % | Peak CPU % | Mean memory MiB | Peak memory MiB |",
        "|---|---:|---:|---:|---:|",
    ]
    for r, metrics in summary["resources"].items():
        cpu, memory = metrics["cpuPercent"], metrics["memoryBytes"]
        lines.append(
            f"| {r} | {cpu['mean']:.2f} | {cpu['max']:.2f} | {memory['mean']/1024**2:.2f} | {memory['max']/1024**2:.2f} |"
            if cpu and memory
            else f"| {r} | unavailable | unavailable | unavailable | unavailable |"
        )
    if heap:
        lines += [
            "",
            f"Sampled mock heap min/mean/max: {heap['min']/1024**2:.2f} / {heap['mean']/1024**2:.2f} / {heap['max']/1024**2:.2f} MiB ({heap['samples']} samples).",
        ]
    else:
        lines += ["", "Mock heap samples unavailable."]
    lines += [
        "",
        "JVM flags: " + "; ".join(summary["jvmEnvironment"]),
        "",
        "[Full summary](summary.json) · [Verdict and minute rates](verdict.json) · [CPU/memory/heap time series](telemetry.jsonl) · [Mock GC]("
        + summary["evidence"]["mockGc"]
        + ")",
        "",
        *summary["limitations"],
    ]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary


def signature(root):
    config = read(root, "config.json")
    sources = read(root, "source-sha256.json")
    containers = read(root, "container-inspect-after.json")
    limits, images, jvm = {}, {}, {}
    for c in containers:
        r = role(c, config["mode"])
        h = c["HostConfig"]
        value = {k: h[k] for k in ("NanoCpus", "Memory", "MemorySwap", "PidsLimit")}
        value["Ulimits"] = h["Ulimits"]
        if r in limits and limits[r] != value:
            raise ValueError("Inconsistent per-engine resource limits")
        limits[r] = value
        if r in images and images[r] != c["Image"]:
            raise ValueError("Inconsistent per-engine images")
        images[r] = c["Image"]
        jvm[r] = sorted(
            v
            for v in c["Config"]["Env"]
            if v.startswith(
                (
                    "JAVA_TOOL_OPTIONS=",
                    "HEAP=",
                    "JVM_ARGS=",
                    "JDK_JAVA_OPTIONS=",
                    "JAVA_OPTS=",
                )
            )
        )
    return dict(
        config={
            k: config[k]
            for k in (
                "target",
                "offered",
                "seconds",
                "warmup",
                "threads",
                "engines",
                "host",
            )
        },
        cases=read(root, "selected-cases.json"),
        limits=limits,
        images=images,
        jvm=jvm,
        measuredSeconds=read(root, "verdict.json")["measuredSeconds"],
        sources={
            k: v
            for k, v in sources.items()
            if k.startswith(("src/", "tests/perf/"))
            or k
            in (
                "Dockerfile",
                "compose.yaml",
                "compose.swarm.yaml",
                "swarm.yaml",
                "pom.xml",
                "tools/fixtures.py",
            )
        },
    )


def validate_pair(baseline, candidate, kind):
    a, b = [read(p, "config.json") for p in (baseline, candidate)]
    if kind == "capture":
        if a["capture"] != "off" or b["capture"] != "on" or a["mode"] != b["mode"]:
            raise ValueError("Capture comparison requires off -> on, same runtime")
    elif (
        a["mode"] != "official"
        or b["mode"] != "headless"
        or a["capture"] != b["capture"]
    ):
        raise ValueError(
            "Runtime comparison requires official -> headless, same capture setting"
        )
    x, y = signature(baseline), signature(candidate)
    if kind == "runtime":
        del x["images"]["mock"]
        del y["images"]["mock"]
    elif (
        read(baseline, "mock-runtime.json")["java"]
        != read(candidate, "mock-runtime.json")["java"]
    ):
        raise ValueError("Capture comparison JVMs differ")
    mismatches = [k for k in x if x[k] != y[k]]
    if mismatches:
        raise ValueError("Unmatched comparison: " + ", ".join(mismatches))
    if not all(read(p, "verdict.json")["pass"] for p in (baseline, candidate)):
        raise ValueError("Both runs must pass; inspect individual failure evidence")


def measures(summary):
    v = summary["verdict"]
    result = {
        "completedRps": v["completedRps"],
        "delayAdjustedP95Ms": v["delayAdjustedLatencyMs"]["p95"],
        "delayAdjustedP99Ms": v["delayAdjustedLatencyMs"]["p99"],
    }
    heap = summary["heapUsedBytes"]
    result["heapPeakBytes"] = heap["max"] if heap else None
    for role_name in ("mock", "total"):
        r = summary["resources"][role_name]
        result[role_name + "MeanCpuPercent"] = (
            r["cpuPercent"]["mean"] if r["cpuPercent"] else None
        )
        result[role_name + "PeakMemoryBytes"] = (
            r["memoryBytes"]["max"] if r["memoryBytes"] else None
        )
    return result


def compare(baseline, candidate, kind):
    baseline, candidate = Path(baseline), Path(candidate)
    validate_pair(baseline, candidate, kind)
    a, b = [summarize(p) for p in (baseline, candidate)]
    left, right = measures(a), measures(b)
    changes = {}
    for key, value in left.items():
        delta = (
            right[key] - value if value is not None and right[key] is not None else None
        )
        changes[key] = dict(
            baseline=value,
            candidate=right[key],
            delta=delta,
            percentChange=(
                100 * delta / value if delta is not None and value != 0 else None
            ),
        )
    result = dict(
        kind=kind,
        baseline=a["runId"],
        candidate=b["runId"],
        changes=changes,
        java=dict(baseline=a["java"], candidate=b["java"]),
        limitation="Observed paired differences at fixed offered rate, not maximum capacity or causal proof. Runtime comparison includes JVM differences.",
    )
    stem = f"comparison-{kind}-{a['runId']}"
    (candidate / (stem + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# " + kind.capitalize() + " comparison",
        "",
        f"Baseline `{a['runId']}` → candidate `{b['runId']}`.",
        "",
        "| Metric | Baseline | Candidate | Delta | Change % |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, values in changes.items():
        cells = ["unavailable" if n is None else f"{n:.3f}" for n in values.values()]
        lines.append("| " + " | ".join([name, *cells]) + " |")
    lines += ["", result["limitation"]]
    (candidate / (stem + ".md")).write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    single = commands.add_parser("summary")
    single.add_argument("run", type=Path)
    pair = commands.add_parser("compare")
    pair.add_argument("--kind", choices=("capture", "runtime"), required=True)
    pair.add_argument("baseline", type=Path)
    pair.add_argument("candidate", type=Path)
    args = parser.parse_args()
    if args.command == "summary":
        summary = write_summary(args.run)
        print(args.run / "REPORT.md")
    else:
        print(json.dumps(compare(args.baseline, args.candidate, args.kind), indent=2))


if __name__ == "__main__":
    main()
