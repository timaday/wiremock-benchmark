import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from swarm import SwarmEngines


class SwarmGateTest(unittest.TestCase):
    def engines(self, root, states):
        tasks = [
            {
                "Status": {
                    "State": state,
                    "ContainerStatus": {"ContainerID": str(i), "ExitCode": code},
                }
            }
            for i, (state, code) in enumerate(states)
        ]

        def call(command, **kwargs):
            text = (
                json.dumps(tasks)
                if "inspect" in command
                else " ".join(str(i) for i in range(len(tasks)))
            )
            return SimpleNamespace(stdout=text)

        return SwarmEngines(root, "example", {}, call)

    def test_a_failed_engine_cannot_be_hidden_by_three_successes(self):
        with tempfile.TemporaryDirectory() as root:
            engines = self.engines(root, [("complete", 0)] * 3 + [("failed", 137)])
            with self.assertRaises(RuntimeError):
                engines.complete()

    def test_replacement_after_failure_cannot_pass(self):
        with tempfile.TemporaryDirectory() as root:
            engines = self.engines(root, [("complete", 0)] * 4 + [("failed", 137)])
            with self.assertRaises(RuntimeError):
                engines.complete()

    def test_missing_fourth_result_cannot_be_merged_as_success(self):
        with tempfile.TemporaryDirectory() as root:
            for i in range(1, 4):
                with (Path(root) / f"engine-{i}.jtl").open("w") as output:
                    writer = csv.writer(output)
                    writer.writerows([["id"], ["setup"], [str(i)]])
            engines = self.engines(root, [("complete", 0)] * 4)
            with self.assertRaises(FileNotFoundError):
                engines.merge()

    def test_log_export_timeout_does_not_prevent_owned_stack_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            commands = []

            def call(command, **kwargs):
                commands.append(command)
                if command[1:3] == ["service", "logs"]:
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return SimpleNamespace(returncode=0)

            engines = SwarmEngines(root, "example", {}, call)
            engines.deployed = True
            engines.logs_and_stop(False)
            self.assertIn(["docker", "stack", "rm", engines.stack], commands)
            status = json.loads((Path(root) / "engine-log-status.json").read_text())
            self.assertFalse(status["complete"])
            self.assertIn("30s", status["reason"])


if __name__ == "__main__":
    unittest.main()
