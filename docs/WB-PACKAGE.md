# WireMock Benchmark CLI

`wiremock-benchmark-cli` installs the `wb` command for configuring, listing,
verifying and explicitly cleaning customer mappings on upstream WireMock.
It needs Python 3.10 or later. Docker and the benchmark repository are not
required on the client machine; apply, verify and clean need network access to
the configured WireMock endpoints.

## Install a release wheel

Install the supplied wheel with [pipx](https://pipx.pypa.io/stable/):

```sh
pipx install /path/to/wiremock_benchmark_cli-0.1.0-py3-none-any.whl
wb --version
wb --help
wb list -f /path/to/wb.yaml --all-customers
```

Alternatively, use a Python virtual environment:

```sh
python3 -m venv ~/.venvs/wiremock-benchmark-cli
. ~/.venvs/wiremock-benchmark-cli/bin/activate
python -m pip install /path/to/wiremock_benchmark_cli-0.1.0-py3-none-any.whl
wb --version
```

Installation resolves the pinned PyYAML dependency. The wheel alone does not
bundle that dependency; offline installations also need its compatible wheel.
No public package-index publication is implied by these instructions.

The distribution name is `wiremock-benchmark-cli`, the Python import package is
`wiremock_benchmark_cli`, and the executable is `wb`.
`python -m wiremock_benchmark_cli` runs the same CLI. Application version `0.1.0`
is independent of YAML `schema_version: 1` and JSON `report_version: 1`.
`--version` and help work without loading configuration or contacting WireMock.

## Configuration and command guide

Use the supplied `wb.yaml` as a starting point, edit its target URLs, then
preview with `wb apply -f wb.yaml --all-mocks --all-customers --dry-run`.
The installed command reads `wb.yaml` in your current directory unless `-f`
selects another file. It never silently loads the packaged example.

See [the command and schema guide](WB.md) for profiles, inheritance, reports,
verification and safe profile switching. Its `./wb` examples work as `wb` after
installation. The wheel also contains unchanged copies of both guides and the
example under `wiremock_benchmark_cli/data/`, retaining their relative links.
To extract them using the Python
interpreter in the installation's virtual environment (existing files are
refused):

```sh
python - <<'PY'
from importlib.resources import files
from pathlib import Path
resources = files("wiremock_benchmark_cli").joinpath("data")
for name in ("wb.yaml", "docs/WB.md", "docs/WB-PACKAGE.md"):
    target = Path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as destination:
        destination.write(resources.joinpath(name).read_bytes())
PY
```

## Develop and build

From the repository root:

```sh
python3 -m venv .runtime/wb-build
. .runtime/wb-build/bin/activate
python -m pip install -e . -r tools/requirements-wb-build.txt
python -m unittest discover -s tools -p 'test_wb*.py'
python -m build
python tools/check_wb_package.py dist/wiremock_benchmark_cli-0.1.0-py3-none-any.whl
```

`python -m build` builds the source distribution, then builds the wheel from
that archive. The artifact check installs the wheel into a new isolated virtual
environment and runs the installed command outside the checkout. It checks
package contents, bundled resources, configuration errors, reports and the
apply/verify/clean workflow against a local HTTP fixture. It does not operate
your configured WireMocks. Integration tests requiring a real WireMock are
separate and remain opt-in.

`pyproject.toml` owns package metadata, runtime dependencies, the console entry
point and the pinned build backend. `wiremock_benchmark_cli/__init__.py` owns
the application version. The build frontend is pinned in
`tools/requirements-wb-build.txt`. Only CLI code, documentation, the example
and CLI tests/build tooling enter the source archive; the wheel excludes tests,
benchmark results, deployment files and local state.

For dependency review, retain an inventory from the installed environment with
`python -m pip inspect > dependencies.json` and run your dependency scanner
against that environment before releasing. Build-tool dependencies belong in
the build environment, not the installed CLI. Configuration and reports can
contain sensitive request/response data; they remain user-managed files and
must not be added to release artifacts.

The build uses the standard [Python project metadata](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
and [Hatch file selection](https://hatch.pypa.io/1.13/config/build/) contracts.
