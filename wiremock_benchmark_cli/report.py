"""Responsibility: collect command evidence and atomically publish explicit JSON reports.

Must not: resolve configuration, infer operation success or act as a state cache.
Contract: docs/WB.md, JSON report version 1.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


_active = ContextVar("wb_report", default=None)


class ReportError(RuntimeError):
    """An explicitly requested report cannot be safely created."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def record(key, value):
    state = _active.get()
    if state is not None and state["data"] is not None:
        state["data"][key] = value


def record_event(event):
    state = _active.get()
    if state is not None and state["data"] is not None:
        state["data"]["events"].append(dict(event))


def record_error(message):
    state = _active.get()
    if state is not None and state["data"] is not None:
        state["data"]["errors"].append(str(message))


def record_source(path, content):
    record("config", {"path": str(Path(path).absolute()),
                      "sha256": hashlib.sha256(content).hexdigest()})


def start_report(args):
    """Validate and reserve staging space before config loading or network activity."""
    if args.overwrite_output and not args.output:
        raise ReportError("--overwrite-output requires --output")
    if not args.output:
        return
    state = _active.get()
    destination = Path(args.output).absolute()
    source = Path(args.config).absolute()
    try:
        if (destination.resolve() == source.resolve()
                or (destination.exists() and source.exists() and destination.samefile(source))):
            raise ReportError("Report destination must not be the input YAML file")
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ReportError("Report destination must be a regular file, not a directory or symlink")
        if destination.exists() and not args.overwrite_output:
            raise ReportError("Report already exists; use --overwrite-output to replace it")
        fd, staging = tempfile.mkstemp(prefix=".wb-report-", dir=destination.parent)
        os.close(fd)
    except (OSError, ValueError) as exc:
        raise ReportError(f"Cannot prepare report destination ({type(exc).__name__})") from exc
    state["destination"] = destination
    state["staging"] = Path(staging)
    state["overwrite"] = args.overwrite_output
    options = vars(args).copy()
    # Invalid API overrides can contain credentials. Only the validated plan
    # records the actual URL; do not persist raw user-supplied override strings.
    if "wiremock_api" in options:
        options["wiremock_api"] = "see resolved targets" if args.wiremock_api else None
    state["data"] = {"report_version": 1, "command": state["command"],
                     "started_at": state["started_at"], "finished_at": None,
                     "status": None, "exit_code": None, "options": options,
                     "config": None, "resolved": None, "events": [],
                     "summary": None, "errors": []}


def finish_report(state, code):
    if state["data"] is None:
        return
    data = state["data"]
    data.update(finished_at=timestamp(), exit_code=code,
                status="interrupted" if code == 130 else "success" if code == 0 else "failed")
    staging = state["staging"]
    try:
        try:
            with staging.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if state["overwrite"]:
                os.replace(staging, state["destination"])
            else:
                # Exclusive publication also protects a file created during the run.
                os.link(staging, state["destination"])
        finally:
            staging.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError) as exc:
        raise ReportError(f"Cannot save report ({type(exc).__name__}); "
                          "any completed WireMock operations remain in effect") from exc


def reported_command(command):
    """Scope optional evidence to one invocation, including direct CLI-handler calls."""
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            state = {"command": command, "started_at": timestamp(), "data": None}
            token = _active.set(state)
            code = 1
            try:
                try:
                    code = function(*args, **kwargs)
                except ReportError as exc:
                    print(f"wb: {exc}", file=sys.stderr)
                    code = 2
                except KeyboardInterrupt:
                    record_error("Command interrupted; attempted mutations may have applied")
                    print("wb: interrupted", file=sys.stderr)
                    code = 130
                except SystemExit as exc:
                    code = exc.code
                    raise
                except ModuleNotFoundError as exc:
                    if exc.name == "yaml":
                        code = 2
                        record_error("PyYAML is required; reinstall wiremock-benchmark-cli with its dependencies")
                    else:
                        record_error(f"Command terminated ({type(exc).__name__})")
                    raise
                except Exception as exc:
                    record_error(f"Command terminated ({type(exc).__name__})")
                    raise
            finally:
                try:
                    finish_report(state, code)
                except ReportError as exc:
                    print(f"wb: {exc}", file=sys.stderr)
                    code = 1
                finally:
                    _active.reset(token)
            return code
        return run
    return decorate
