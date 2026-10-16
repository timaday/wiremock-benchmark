"""Responsibility: verify the built CLI artifact through an isolated installation.

Must not: import checkout runtime code or contact configured user environments.
Contract: docs/WB-PACKAGE.md; local HTTP fixture implements the tested API subset.
"""

import argparse
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import venv
from zipfile import ZipFile


class WireMockFixture:
    """Expose a minimal admin/public API and retain observable HTTP effects."""

    def __init__(self):
        self.mappings = {}
        self.probes = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                route = self.path.removeprefix("/mock-1")
                prefix = "/__admin/mappings"
                status, data, headers = 200, b"", {}
                if route.startswith(prefix):
                    identifier = route.removeprefix(prefix).lstrip("/")
                    if self.command == "GET":
                        payload = (owner.mappings.get(identifier) if identifier else
                                   {"mappings": list(owner.mappings.values()),
                                    "meta": {"total": len(owner.mappings)}})
                        status = 200 if payload is not None else 404
                    elif self.command == "DELETE":
                        owner.mappings.pop(identifier, None)
                        payload = {}
                    else:
                        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        owner.mappings[payload["id"]] = payload
                        status = 201 if self.command == "POST" else 200
                    data = json.dumps(payload).encode()
                    headers = {"Content-Type": "application/json"}
                else:
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                    owner.probes.append((self.command, route, body))
                    mapping = next((m for m in owner.mappings.values()
                                    if m["request"]["urlPath"] == route
                                    and m["request"]["method"] == self.command), None)
                    if mapping is None:
                        status = 404
                    else:
                        response = mapping["response"]
                        time.sleep(response["fixedDelayMilliseconds"] / 1000)
                        status, headers = response["status"], response["headers"]
                        data = (json.dumps(response["jsonBody"]).encode() if "jsonBody" in response
                                else response["body"].encode())
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = handle_request

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_wheel(wheel):
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        require(len(metadata_paths) == 1, "Expected exactly one package metadata record")
        metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        require(metadata["Name"] == "wiremock-benchmark-cli", "Wrong distribution name")
        metadata_root = metadata_paths[0].rsplit("/", 1)[0] + "/"
        require(all(name.startswith(("wiremock_benchmark_cli/", metadata_root)) for name in names),
                "Wheel contains files outside the CLI package and its metadata")
        require(all(name.endswith(".py") or name in (
            "wiremock_benchmark_cli/data/wb.yaml",
            "wiremock_benchmark_cli/data/docs/WB.md",
            "wiremock_benchmark_cli/data/docs/WB-PACKAGE.md")
            for name in names if name.startswith("wiremock_benchmark_cli/")),
            "Unexpected runtime package contents")
        entrypoints = archive.read(metadata_root + "entry_points.txt").decode()
        require("wb = wiremock_benchmark_cli.cli:main" in entrypoints, "Missing wb entry point")
        for resource in ("wb.yaml", "docs/WB.md", "docs/WB-PACKAGE.md"):
            require(bool(archive.read("wiremock_benchmark_cli/data/" + resource)), "Empty resource")
        return metadata["Version"]


def check_install(wheel, root, version):
    environment = root / "environment"
    work = root / "work"
    work.mkdir()
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    wb = scripts / ("wb.exe" if os.name == "nt" else "wb")
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONNOUSERSITE"] = "1"

    def run(*args, expected=0, timeout=30):
        result = subprocess.run([str(arg) for arg in args], cwd=work, env=env,
                                capture_output=True, text=True, timeout=timeout)
        require(result.returncode == expected,
                f"{Path(args[0]).name} exited {result.returncode}, expected {expected}:\n"
                f"{result.stdout}\n{result.stderr}")
        return result.stdout

    run(python, "-m", "pip", "install", "--disable-pip-version-check", wheel, timeout=180)
    run(python, "-m", "pip", "check")
    require(run(wb, "--version").strip() == f"wiremock-benchmark-cli {version}", "Version mismatch")
    require(run(python, "-m", "wiremock_benchmark_cli", "--version") == run(wb, "--version"),
            "Module and console versions differ")
    location = Path(run(python, "-c", "import wiremock_benchmark_cli; print(wiremock_benchmark_cli.__file__)").strip())
    require(location.is_relative_to(environment), "Imported the checkout instead of installed package")
    for command in ([], ["apply"], ["list"], ["verify"], ["clean"]):
        for flag in ("--help", "--h", "-h"):
            require("Examples:" in run(wb, *command, flag), "Missing installed help")
    run(python, "-c", "from importlib.resources import files; from pathlib import Path; "
        "r = files('wiremock_benchmark_cli').joinpath('data'); "
        "Path('example.yaml').write_bytes(r.joinpath('wb.yaml').read_bytes()); "
        "assert r.joinpath('docs/WB.md').read_text(); "
        "assert r.joinpath('docs/WB-PACKAGE.md').read_text()")
    run(wb, "list", "-f", "example.yaml", "--all-customers", "--output", "example-report.json")
    run(wb, "list", "-f", "missing.yaml", "--all-customers", "--output", "failure.json", expected=2)
    require(json.loads((work / "failure.json").read_text())["status"] == "failed", "Missing failure report")

    with WireMockFixture() as fixture:
        base = f"http://127.0.0.1:{fixture.server.server_port}/mock-1"
        config = f"""schema_version: 1
wiremocks:
  mock-1:
    api: {base}
    prefix_handling: strip
    customers:
      demo: {{}}
customers:
  demo:
    name: Demo
    endpoint_scope: product-class
    response_profile: empty-ok
    delay_ms: 0
    ProductClasses:
      One:
      Two:
response_profiles:
  empty-ok:
    status: 200
    headers: {{}}
    body: ''
    request_profile: text-post
request_profiles:
  text-post:
    method: POST
    probe_body:
      type: text
      value: package-check
error_profiles: {{}}
customer_groups: {{}}
"""
        (work / "profile.yaml").write_text(config)

        def invoke(command, report, *extra):
            run(wb, command, "-f", "profile.yaml", "--mock", "mock-1", "--customer", "demo",
                "--output", report, *extra)
            return json.loads((work / report).read_text())

        invoke("apply", "preview.json", "--dry-run")
        require(not fixture.mappings, "Dry-run created mappings")
        require(invoke("apply", "apply.json")["summary"] == {"verified": 2}, "Apply not verified")
        original_ids = set(fixture.mappings)
        invoke("apply", "reapply.json")
        require(set(fixture.mappings) == original_ids, "Reapply changed stable IDs")
        require(invoke("verify", "verify.json")["summary"] == {"passed": 2, "failed": 0}, "Probe failed")
        require(len(fixture.probes) == 2 and all(p[2] == b"package-check" for p in fixture.probes),
                "Request profile probe body not sent")
        # Switch One+Two to Two+Three, then remove only the obsolete owned mapping.
        (work / "profile.yaml").write_text(config.replace("      One:\n", "      Three:\n"))
        invoke("apply", "switch.json")
        require(len(fixture.mappings) == 3, "Switch did not retain obsolete mapping until cleanup")
        preview = invoke("clean", "clean-preview.json", "--stale-only", "--dry-run")
        require(preview["summary"]["candidates"] == 1 and len(fixture.mappings) == 3, "Invalid cleanup preview")
        deleted = invoke("clean", "clean.json", "--stale-only", "--execute")
        require(deleted["summary"]["deleted"] == 1 and len(fixture.mappings) == 2, "Cleanup did not converge")
        require(invoke("verify", "switched-verify.json")["summary"] == {"passed": 2, "failed": 0},
                "Switched profile failed verification")
        require(invoke("clean", "final-preview.json", "--stale-only")["summary"]["candidates"] == 0,
                "Obsolete mappings remain")
    print(f"PASS: {wheel.name}; isolated install, resources, reports, HTTP probes and profile switching")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    version = check_wheel(wheel)
    with tempfile.TemporaryDirectory(prefix="wb-package-check-") as directory:
        check_install(wheel, Path(directory), version)


if __name__ == "__main__":
    main()
