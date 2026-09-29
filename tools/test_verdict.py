import csv, json, sqlite3, tempfile, unittest
from pathlib import Path
from verdict import evaluate


class VerdictTest(unittest.TestCase):
    def fixture(self, rows):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "window.json").write_text(
            json.dumps({"startMs": 100000, "endMs": 160000})
        )
        (root / "config.json").write_text(json.dumps({"runId": "test", "offered": 1}))
        fields = [
            "timeStamp",
            "elapsed",
            "success",
            "bench_id",
            "case_id",
            "delay_ms",
            "payload_bytes",
            "request_sha256",
            "response_sha256",
        ]
        with (root / "samples.csv").open("w") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i in range(rows):
                writer.writerow(
                    dict(
                        timeStamp=100000 + i * 1000,
                        elapsed=1,
                        success="true",
                        bench_id=str(i),
                        case_id="x",
                        delay_ms=0,
                        payload_bytes=1024,
                        request_sha256="a",
                        response_sha256="b",
                    )
                )
        return tmp, root

    def test_shortfall_is_failure_even_with_zero_errors(self):
        tmp, root = self.fixture(59)
        with tmp:
            self.assertFalse(evaluate(root, None, 1, False, {})["pass"])

    def test_exact_minute_target_is_supported(self):
        tmp, root = self.fixture(60)
        with tmp:
            self.assertTrue(evaluate(root, None, 1, False, {})["pass"])

    def test_missing_capture_is_failure(self):
        tmp, root = self.fixture(60)
        with tmp:
            archive = root / "archive.db"
            with sqlite3.connect(archive) as db:
                db.execute(
                    "CREATE TABLE events(run_id TEXT,request_id TEXT, phase TEXT, body_sha256 TEXT, body_bytes INTEGER)"
                )
            result = evaluate(root, archive, 1, True, dict(pending=0, errors=0))
            self.assertFalse(result["pass"])
            self.assertEqual(60, result["capture"]["missingOrCorruptExchanges"])

    def test_repeated_evaluation_is_deterministic(self):
        tmp, root = self.fixture(60)
        with tmp:
            self.assertTrue(evaluate(root, None, 1, False, {})["pass"])
            self.assertTrue(evaluate(root, None, 1, False, {})["pass"])

    def test_corrupted_response_capture_fails_despite_matching_count(self):
        tmp, root = self.fixture(60)
        with tmp:
            archive = root / "archive.db"
            with sqlite3.connect(archive) as db:
                db.execute(
                    "CREATE TABLE events(run_id TEXT,request_id TEXT,phase TEXT,body_sha256 TEXT,body_bytes INTEGER)"
                )
                for i in range(60):
                    for phase, digest, size in [
                        ("REQUEST", "a", 1024),
                        ("RESPONSE_PREPARED", "wrong", 1024),
                        ("SEND_COMPLETED", "empty", 0),
                    ]:
                        db.execute(
                            "INSERT INTO events VALUES(?,?,?,?,?)",
                            ("test", str(i), phase, digest, size),
                        )
            result = evaluate(root, archive, 1, True, dict(pending=0, errors=0))
            self.assertEqual(180, result["capture"]["events"])
            self.assertEqual(60, result["capture"]["missingOrCorruptExchanges"])
            self.assertFalse(result["pass"])

    def test_stop_before_warmup_cannot_pass(self):
        tmp, root = self.fixture(60)
        with tmp:
            (root / "window.json").write_text(
                json.dumps({"startMs": 100000, "endMs": 99999})
            )
            with self.assertRaises(ValueError):
                evaluate(root, None, 1, False, {})

    def test_catchup_burst_cannot_pass_as_the_configured_rate(self):
        tmp, root = self.fixture(120)
        with tmp:
            path = root / "samples.csv"
            with path.open() as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                rows = list(reader)
            with path.open("w") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for i, row in enumerate(rows):
                    row["timeStamp"] = 100000 + i * 500
                    writer.writerow(row)
            result = evaluate(root, None, 1, False, {})
            self.assertTrue(result["checks"]["averageCompletedTarget"])
            self.assertFalse(result["checks"]["scheduledRateRespected"])
            self.assertFalse(result["pass"])

    def test_injection_shortfall_fails_even_when_lower_target_passes(self):
        tmp, root = self.fixture(60)
        with tmp:
            (root / "config.json").write_text(
                json.dumps({"runId": "test", "offered": 2})
            )
            result = evaluate(root, None, 1, False, {})
            self.assertTrue(result["checks"]["averageCompletedTarget"])
            self.assertFalse(result["checks"]["scheduledRateRespected"])

    def test_missing_identity_is_not_silently_dropped(self):
        tmp, root = self.fixture(60)
        with tmp:
            path = root / "samples.csv"
            with path.open() as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                rows = list(reader)
            rows[0]["bench_id"] = ""
            with path.open("w") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(ValueError):
                evaluate(root, None, 1, False, {})


if __name__ == "__main__":
    unittest.main()
