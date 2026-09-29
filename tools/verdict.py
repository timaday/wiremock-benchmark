"""Streaming CSV verdict with disk-backed identity reconciliation; never averages away failed minutes."""

import csv, json, math, sqlite3, time
from collections import Counter
from pathlib import Path


def evaluate(result_dir, archive, target, capture, metrics):
    root = Path(result_dir)
    config = json.loads((root / "config.json").read_text())
    window = json.loads((root / "window.json").read_text())
    start, end = window["startMs"], window["endMs"]
    if end <= start:
        raise ValueError("Run stopped before its measurement window")
    seconds = (end - start) / 1000
    reconciliation = root / "reconciliation.db"
    if reconciliation.exists():
        reconciliation.rename(root / f"reconciliation-{time.time_ns()}.db")
    db = sqlite3.connect(reconciliation)
    db.execute(
        "CREATE TABLE expected(id TEXT PRIMARY KEY,request_sha TEXT,response_sha TEXT,size INTEGER)"
    )
    starts = Counter()
    completions = Counter()
    latency = Counter()
    overhead = Counter()
    total = errors = duplicate = 0
    batch = []
    with (root / "samples.csv").open() as stream:
        for row in csv.DictReader(stream):
            if row.get("bench_id") in [None, "", "null"] or row.get("case_id") in [
                None,
                "",
                "null",
            ]:
                raise ValueError(
                    "HTTP sample lacks required correlation/workload metadata"
                )
            timestamp = int(row["timeStamp"])
            elapsed = int(row["elapsed"])
            if start <= timestamp + elapsed < end and row["success"] == "true":
                completions[(timestamp + elapsed - start) // 60000] += 1
            if not start <= timestamp < end:
                continue
            total += 1
            errors += row["success"] != "true"
            starts[(timestamp - start) // 60000] += 1
            latency[elapsed] += 1
            overhead[elapsed - int(row["delay_ms"])] += 1
            batch.append(
                (
                    row["bench_id"],
                    row["request_sha256"],
                    row["response_sha256"],
                    int(row["payload_bytes"]),
                )
            )
            if len(batch) >= 2000:
                before = db.total_changes
                db.executemany("INSERT OR IGNORE INTO expected VALUES(?,?,?,?)", batch)
                duplicate += len(batch) - (db.total_changes - before)
                db.commit()
                batch = []
    if batch:
        before = db.total_changes
        db.executemany("INSERT OR IGNORE INTO expected VALUES(?,?,?,?)", batch)
        duplicate += len(batch) - (db.total_changes - before)
        db.commit()

    def percentiles(hist):
        size = sum(hist.values())
        output = {}
        acc = 0
        wanted = [(0.5, "p50"), (0.95, "p95"), (0.99, "p99")]
        for value, count in sorted(hist.items()):
            acc += count
            for q, name in wanted:
                if name not in output and acc >= math.ceil(size * q):
                    output[name] = value
        output["max"] = max(hist, default=None)
        return output

    minutes = [
        {"minute": i, "startedRps": starts[i] / 60, "completedRps": completions[i] / 60}
        for i in range(int(seconds // 60))
    ]
    capture_result = {"enabled": capture}
    if capture:
        db.execute(
            "ATTACH DATABASE ? AS capture", (f"file:{Path(archive).resolve()}?mode=ro",)
        )
        run_id = json.loads((root / "config.json").read_text())["runId"]
        count = db.execute(
            "SELECT count(*) FROM capture.events e JOIN expected x ON e.request_id=x.id WHERE e.run_id=?",
            (run_id,),
        ).fetchone()[0]
        missing = db.execute(
            "SELECT count(*) FROM expected x WHERE NOT EXISTS(SELECT 1 FROM capture.events e WHERE e.run_id=? AND e.request_id=x.id AND e.phase='REQUEST' AND e.body_sha256=x.request_sha AND e.body_bytes=x.size) OR NOT EXISTS(SELECT 1 FROM capture.events e WHERE e.run_id=? AND e.request_id=x.id AND e.phase='RESPONSE_PREPARED' AND e.body_sha256=x.response_sha AND e.body_bytes=x.size) OR NOT EXISTS(SELECT 1 FROM capture.events e WHERE e.run_id=? AND e.request_id=x.id AND e.phase='SEND_COMPLETED')",
            (run_id, run_id, run_id),
        ).fetchone()[0]
        capture_result.update(
            events=count,
            expectedEvents=total * 3,
            missingOrCorruptExchanges=missing,
            pending=metrics["pending"],
            errors=metrics["errors"],
        )
        capture_ok = (
            count == total * 3
            and missing == 0
            and metrics["pending"] == 0
            and metrics["errors"] == 0
        )
    else:
        capture_ok = True
    checks = {
        "httpCorrect": total > 0 and errors == 0,
        "uniqueClientIds": duplicate == 0,
        "averageOfferedTarget": total / seconds >= target,
        "averageCompletedTarget": sum(completions.values()) / seconds >= target,
        "everyFullMinuteAtTarget": all(
            m["startedRps"] >= target and m["completedRps"] >= target for m in minutes
        ),
        "captureReconciled": capture_ok,
        "scheduledRateRespected": seconds < 60
        or (
            config["offered"] * 0.95 <= total / seconds <= config["offered"] * 1.05
            and all(
                config["offered"] * 0.95 <= m["startedRps"] <= config["offered"] * 1.05
                for m in minutes
            )
        ),
    }
    report = {
        "pass": all(checks.values()),
        "checks": checks,
        "measuredSeconds": seconds,
        "targetRps": target,
        "measuredRequests": total,
        "errors": errors,
        "offeredRps": total / seconds,
        "completedRps": sum(completions.values()) / seconds,
        "minutes": minutes,
        "latencyMs": percentiles(latency),
        "delayAdjustedLatencyMs": percentiles(overhead),
        "capture": capture_result,
    }
    (root / "verdict.json").write_text(json.dumps(report, indent=2))
    db.close()
    return report
