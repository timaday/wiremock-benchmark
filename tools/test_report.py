import json
import tempfile
import unittest
from pathlib import Path

from report import compare, memory_bytes, summarize, validate_pair


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / "off", self.root / "on"
        for root, capture in ((self.a, "off"), (self.b, "on")):
            root.mkdir()
            self.write(
                root,
                "config.json",
                dict(
                    runId=root.name,
                    mode="official",
                    capture=capture,
                    target=10,
                    offered=12,
                    seconds=60,
                    warmup=60,
                    threads=32,
                    engines=4,
                    host={"machine": "test"},
                ),
            )
            self.write(root, "window.json", dict(startMs=1000, endMs=10000))
            self.write(root, "mock-runtime.json", {"java": "test-java"})
            self.write(root, "source-sha256.json", {"src/Example.java": "same"})
            self.write(
                root,
                "selected-cases.json",
                [{"id": "json-1024-0", "size": 1024, "delay": 0, "template": "json"}],
            )
            self.write(
                root,
                "verdict.json",
                {
                    "pass": True,
                    "measuredSeconds": 60,
                    "completedRps": 12,
                    "delayAdjustedLatencyMs": {"p95": 3, "p99": 5},
                },
            )
            container = dict(
                Name="/mock",
                Image="mock-image",
                Config=dict(
                    Labels={"com.docker.compose.service": "official"},
                    Env=["JAVA_TOOL_OPTIONS=-Xmx3g"],
                ),
                HostConfig=dict(
                    NanoCpus=4e9,
                    Memory=4 * 1024**3,
                    MemorySwap=4 * 1024**3,
                    PidsLimit=1024,
                    Ulimits=[],
                ),
            )
            self.write(root, "container-inspect-after.json", [container])
            rows = []
            for timestamp, heap, cpu, memory in (
                (0, 9999, 99, "100MiB"),
                (2, 200, 10, "10MiB"),
                (8, 400, 30, "20MiB"),
                (11, 9999, 99, "100MiB"),
            ):
                rows.append(
                    dict(
                        timestamp=timestamp,
                        metrics=dict(heapUsed=heap),
                        containers=json.dumps(
                            dict(
                                Name="mock",
                                CPUPerc=f"{cpu}%",
                                MemUsage=f"{memory} / 4GiB",
                            )
                        ),
                    )
                )
            (root / "telemetry.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows)
            )

    def write(self, root, name, value):
        (root / name).write_text(json.dumps(value))

    def change(self, root, name, field, value):
        data = json.loads((root / name).read_text())
        data[field] = value
        self.write(root, name, data)

    def test_excludes_warmup_and_drain_from_resource_summary(self):
        result = summarize(self.a)
        self.assertEqual(
            result["heapUsedBytes"], dict(samples=2, min=200, mean=300, max=400)
        )
        self.assertEqual(result["resources"]["mock"]["cpuPercent"]["mean"], 20)
        self.assertEqual(
            result["resources"]["total"]["memoryBytes"]["max"], 20 * 1024**2
        )

    def test_missing_samples_are_not_reported_as_zero(self):
        (self.a / "telemetry.jsonl").write_text(
            json.dumps(dict(timestamp=3, error="unavailable")) + "\n"
        )
        result = summarize(self.a)
        self.assertIsNone(result["heapUsedBytes"])
        self.assertIsNone(result["resources"]["total"]["cpuPercent"])
        self.assertEqual(result["telemetryErrors"], 1)

    def test_partial_container_sample_is_not_a_complete_stack_total(self):
        containers = json.loads((self.a / "container-inspect-after.json").read_text())
        engine = json.loads(json.dumps(containers[0]))
        engine["Name"] = "/injector"
        engine["Config"]["Labels"] = {"com.docker.swarm.service.name": "injector"}
        self.write(self.a, "container-inspect-after.json", [*containers, engine])
        result = summarize(self.a)
        self.assertEqual(result["resources"]["mock"]["cpuPercent"]["mean"], 20)
        self.assertIsNone(result["resources"]["total"]["cpuPercent"])

    def test_memory_unit_conversion(self):
        self.assertEqual(memory_bytes("1.5GiB"), 1.5 * 1024**3)
        self.assertEqual(memory_bytes("2MB"), 2000000)
        with self.assertRaises(ValueError):
            memory_bytes("unknown")

    def test_capture_pair_calculates_actual_difference(self):
        data = json.loads((self.b / "verdict.json").read_text())
        data["delayAdjustedLatencyMs"]["p95"] = 9
        self.write(self.b, "verdict.json", data)
        result = compare(self.a, self.b, "capture")
        self.assertEqual(result["changes"]["delayAdjustedP95Ms"]["delta"], 6)
        self.assertEqual(result["changes"]["delayAdjustedP95Ms"]["percentChange"], 200)
        self.assertTrue((self.b / "comparison-capture-off.md").exists())

    def test_mismatched_threads_and_payloads_are_rejected(self):
        self.change(self.b, "config.json", "threads", 40)
        with self.assertRaisesRegex(ValueError, "config"):
            validate_pair(self.a, self.b, "capture")
        self.change(self.b, "config.json", "threads", 32)
        self.write(self.b, "selected-cases.json", [])
        with self.assertRaisesRegex(ValueError, "cases"):
            validate_pair(self.a, self.b, "capture")

    def test_failed_run_cannot_support_overhead_claim(self):
        self.change(self.b, "verdict.json", "pass", False)
        with self.assertRaisesRegex(ValueError, "must pass"):
            validate_pair(self.a, self.b, "capture")

    def test_unmatched_jvm_rejected_for_capture(self):
        self.change(self.b, "mock-runtime.json", "java", "another-java")
        with self.assertRaisesRegex(ValueError, "JVMs differ"):
            validate_pair(self.a, self.b, "capture")

    def test_runtime_pair_allows_only_intended_runtime_difference(self):
        self.change(self.a, "config.json", "capture", "on")
        self.change(self.b, "config.json", "mode", "headless")
        self.change(self.b, "mock-runtime.json", "java", "another-java")
        containers = json.loads((self.b / "container-inspect-after.json").read_text())
        containers[0]["Config"]["Labels"]["com.docker.compose.service"] = "headless"
        containers[0]["Image"] = "headless-image"
        self.write(self.b, "container-inspect-after.json", containers)
        validate_pair(self.a, self.b, "runtime")
        containers[0]["HostConfig"]["Memory"] = 99
        self.write(self.b, "container-inspect-after.json", containers)
        with self.assertRaisesRegex(ValueError, "limits"):
            validate_pair(self.a, self.b, "runtime")


if __name__ == "__main__":
    unittest.main()
