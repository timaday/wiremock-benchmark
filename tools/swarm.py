"""Four independent JMeter CLI tasks in an explicitly owned Docker Swarm stack."""

import csv
import json
import math
import subprocess
import time
from pathlib import Path

ENGINE_COUNT = 4


class SwarmEngines:
    def __init__(self, root, identifier, environment, call):
        self.root = Path(root)
        self.identifier = identifier
        self.environment = environment.copy()
        self.call = call
        self.stack = "wmb-" + identifier + "-engines"
        self.service = self.stack + "_injector"
        self.network = "wmb-" + identifier + "-overlay"
        self.container_ids = []
        self.network_created = False
        self.deployed = False

    def prepare(self):
        swarm = json.loads(
            self.call(["docker", "info", "--format", "{{json .Swarm}}"]).stdout
        )
        if not swarm["ControlAvailable"]:
            raise RuntimeError("Run requires a Docker Swarm manager; see README setup")
        self.environment.update(BENCH_NODE=swarm["NodeID"], BENCH_NETWORK=self.network)
        self.call(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "overlay",
                "--attachable",
                self.network,
            ]
        )
        self.network_created = True
        return self.network

    def start(self, mode, offered, threads, case, warmup, seconds):
        load_start = int(time.time() * 1000) + 30000
        window = dict(
            startedMs=load_start,
            startMs=load_start + warmup * 1000,
            endMs=load_start + (warmup + seconds) * 1000,
        )
        (self.root / "window.json").write_text(json.dumps(window))
        self.environment.update(
            BENCH_HOST=mode,
            ENGINE_RATE=str(offered / ENGINE_COUNT),
            ENGINE_THREADS=str(math.ceil(threads / ENGINE_COUNT)),
            LOAD_START_MS=str(load_start),
            MEASURE_END_MS=str(window["endMs"]),
            BENCH_CASE=case,
            RESULTS_PATH=str(self.root.parent.resolve()),
        )
        self.deployed = True
        with (self.root / "engine-deployment.log").open("w") as output:
            self.call(
                [
                    "docker",
                    "stack",
                    "deploy",
                    "--resolve-image",
                    "never",
                    "-c",
                    "swarm.yaml",
                    self.stack,
                ],
                env=self.environment,
                output=output,
            )
        inspection = self.call(["docker", "service", "inspect", self.service]).stdout
        (self.root / "engine-service.json").write_text(inspection)
        actual = dict(
            value.split("=", 1)
            for value in json.loads(inspection)[0]["Spec"]["TaskTemplate"][
                "ContainerSpec"
            ]["Env"]
        )
        for name in [
            "ENGINE_RATE",
            "ENGINE_THREADS",
            "LOAD_START_MS",
            "MEASURE_END_MS",
            "RUN_ID",
            "BENCH_HOST",
        ]:
            expected = self.identifier if name == "RUN_ID" else self.environment[name]
            if actual.get(name) != expected:
                raise RuntimeError(
                    "Swarm did not preserve explicit engine setting: " + name
                )

    def complete(self):
        identifiers = self.call(
            ["docker", "service", "ps", "-q", self.service]
        ).stdout.split()
        if not identifiers:
            return False
        tasks = json.loads(
            self.call(["docker", "inspect", "--type", "task", *identifiers]).stdout
        )
        (self.root / "engine-tasks.json").write_text(json.dumps(tasks, indent=2))
        self.container_ids = [
            task["Status"]["ContainerStatus"]["ContainerID"]
            for task in tasks
            if task["Status"].get("ContainerStatus", {}).get("ContainerID")
        ]
        if len(tasks) > ENGINE_COUNT:
            raise RuntimeError("An engine task was replaced; run cannot pass")
        for task in tasks:
            status = task["Status"]
            if status["State"] in [
                "failed",
                "rejected",
                "shutdown",
                "orphaned",
                "remove",
            ]:
                raise RuntimeError(
                    "Engine task failed: "
                    + status["State"]
                    + " "
                    + status.get("Err", "")
                )
            if (
                status["State"] == "complete"
                and status.get("ContainerStatus", {}).get("ExitCode") != 0
            ):
                raise RuntimeError("Engine completed without a successful exit code")
        return len(tasks) == ENGINE_COUNT and all(
            task["Status"]["State"] == "complete" for task in tasks
        )

    def graceful_stop(self):
        for identifier in self.container_ids:
            self.call(
                [
                    "docker",
                    "exec",
                    identifier,
                    "/opt/apache-jmeter-5.6.3/bin/shutdown.sh",
                ],
                check=False,
            )

    def merge(self):
        header = None
        counts = {}
        with (self.root / "samples.jtl").open("w", newline="") as output:
            writer = csv.writer(output)
            for engine in range(1, ENGINE_COUNT + 1):
                path = self.root / f"engine-{engine}.jtl"
                count = 0
                with path.open(newline="") as source:
                    reader = csv.reader(source)
                    current = next(reader)
                    if header is None:
                        header = current
                        writer.writerow(header)
                    elif current != header:
                        raise ValueError("Engine JTL headers differ")
                    for row in reader:
                        writer.writerow(row)
                        count += 1
                if count <= 1:
                    raise ValueError(f"Engine {engine} supplied no HTTP samples")
                counts[str(engine)] = count
        (self.root / "engine-sample-counts.json").write_text(
            json.dumps(counts, indent=2)
        )

    def logs_and_stop(self, keep):
        if self.deployed:
            try:
                with (self.root / "injector.log").open("w") as output:
                    result = self.call(
                        [
                            "docker",
                            "service",
                            "logs",
                            "--raw",
                            "--timestamps",
                            self.service,
                        ],
                        output=output,
                        check=False,
                        timeout=30,
                    )
                status = {
                    "complete": result.returncode == 0,
                    "exitCode": result.returncode,
                }
            except subprocess.TimeoutExpired:
                status = {
                    "complete": False,
                    "reason": "Service-log export exceeded 30s",
                }
            finally:
                if not keep:
                    self.call(["docker", "stack", "rm", self.stack], check=False)
            (self.root / "engine-log-status.json").write_text(
                json.dumps(status, indent=2)
            )
            if not status["complete"]:
                print(
                    json.dumps(
                        {
                            "diagnosticWarning": "Aggregate engine logs incomplete",
                            "details": status,
                        }
                    ),
                    flush=True,
                )

    def remove_network(self, keep):
        if keep or not self.network_created:
            return
        deadline = time.monotonic() + 60
        while True:
            result = self.call(["docker", "network", "rm", self.network], check=False)
            if result.returncode == 0:
                return
            if time.monotonic() > deadline:
                raise RuntimeError("Owned overlay cleanup failed: " + self.network)
            time.sleep(1)
