import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import qualify
from bench import select_cases
from fixtures import generate, SIZES, TEMPLATES


class QualificationTest(unittest.TestCase):
    def test_fixed_delay_keeps_every_size_and_template(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = generate(directory)
        for delay in (2000, 6000):
            chosen = select_cases(cases, "mixed", delay)
            self.assertEqual({c["delay"] for c in chosen}, {delay})
            self.assertEqual(
                {(c["size"], c["template"]) for c in chosen},
                {(s, t) for s in SIZES for t in TEMPLATES},
            )
        with self.assertRaises(ValueError):
            select_cases(cases, "json-1024-6000", 6000)

    def test_fixed_and_subset_payloads_across_delays(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = generate(directory)
        fixed = select_cases(cases, "mixed", None, [10], ["json", "text"])
        self.assertEqual({c["size"] for c in fixed}, {10240})
        self.assertEqual(len(fixed), 16)
        subset = select_cases(cases, "mixed", 0, [1, 50], ["json"])
        self.assertEqual({c["size"] for c in subset}, {1024, 51200})
        with self.assertRaises(ValueError):
            select_cases(cases, "json-1024-0", None, [1])

    def test_six_seconds_runs_official_then_headless(self):
        self.assertEqual(
            qualify.schedule([6000]),
            [dict(mode="official", delayMs=6000), dict(mode="headless", delayMs=6000)],
        )
        self.assertEqual(len(qualify.schedule()), 16)
        self.assertEqual(qualify.required_bytes(2), 34 * qualify.GIB)

    def test_resume_requires_a_full_hour_verdict(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            qualify, "ROOT", Path(directory)
        ):
            root = Path(directory) / "results" / "example"
            root.mkdir(parents=True)
            (root / "config.json").write_text(
                json.dumps({"generator": qualify.GENERATOR})
            )
            verdict = root / "verdict.json"
            attempt = dict(state="passed", runId="example")
            verdict.write_text(json.dumps({"pass": True, "measuredSeconds": 1800}))
            self.assertFalse(qualify.completed(attempt))
            verdict.write_text(json.dumps({"pass": True, "measuredSeconds": 3600}))
            self.assertTrue(qualify.completed(attempt))
            (root / "config.json").write_text(json.dumps({"generator": "jmeter-5.6.3"}))
            self.assertFalse(qualify.completed(attempt))

    def test_failure_stops_sequence_and_restores_only_paused_containers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = root / "results" / "suite-test"
            suite.mkdir(parents=True)
            commands = []

            def command(args, **kwargs):
                commands.append(args)
                return SimpleNamespace(
                    stdout="owned1\nowned2\n" if "--status" in args else ""
                )

            child = SimpleNamespace(
                stdout=io.StringIO("failed\n"), wait=lambda: 1, poll=lambda: 1
            )
            args = SimpleNamespace(
                max_runs=None,
                execute=True,
                pause_project="owned",
                pause_file="/test/compose.yaml",
            )
            state = dict(
                generator=qualify.GENERATOR,
                state="planned",
                attempts=[],
                workload=dict(sizeKiB=[10], templates=["json"]),
                schedule=qualify.schedule([6000]),
            )
            with patch.object(qualify, "ROOT", root), patch.object(
                qualify, "command", command
            ), patch.object(
                qualify.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1000 * qualify.GIB),
            ), patch.object(
                qualify.subprocess, "Popen", return_value=child
            ) as launch:
                with self.assertRaisesRegex(RuntimeError, "Run failed"):
                    qualify.run_suite(args, suite, state)
            self.assertEqual(launch.call_count, 1)
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index("--size-kib") + 1], "10")
            self.assertEqual(command[command.index("--template") + 1], "json")
            self.assertIn(["docker", "start", "owned1", "owned2"], commands)
            self.assertEqual(state["restoration"], "started")
            self.assertEqual(state["state"], "failed")


if __name__ == "__main__":
    unittest.main()
