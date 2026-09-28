"""One catalogue generates exact byte fixtures and independent response expectations."""

import json
from pathlib import Path

SIZES = [1024, 5120, 10240, 51200]
DELAYS = [0, 1000, 1500, 2000, 3000, 4000, 5000, 6000]
TEMPLATES = ["static", "json", "text"]
ID_LENGTH = 29


def response(kind, size, identifier):
    if kind == "static":
        prefix = '{"kind":"static","padding":"'
        suffix = '"}'
    elif kind == "json":
        prefix = '{"kind":"json","id":"' + identifier + '","padding":"'
        suffix = '"}'
    elif kind == "text":
        prefix, suffix = "id=" + identifier + ";kind=text;padding=", ""
    else:
        raise ValueError(kind)
    return prefix + "x" * (size - len(prefix.encode()) - len(suffix)) + suffix


def generate(root):
    root = Path(root)
    (root / "mappings").mkdir(parents=True, exist_ok=True)
    cases = []
    for size in SIZES:
        for delay in DELAYS:
            for kind in TEMPLATES:
                case_id = f"{kind}-{size}-{delay}"
                sample = response(kind, size, "0" * ID_LENGTH)
                assert len(sample.encode()) == size
                template = (
                    sample.replace("0" * ID_LENGTH, "{{request.headers.X-Bench-Id}}")
                    if kind != "static"
                    else sample
                )
                case = dict(
                    id=case_id, size=size, delay=delay, template=kind, example=sample
                )
                cases.append(case)
                mapping = {
                    "request": {"method": "POST", "urlPath": "/bench/" + case_id},
                    "response": {
                        "status": 200,
                        "body": template,
                        "fixedDelayMilliseconds": delay,
                        "headers": {
                            "Content-Type": (
                                "text/plain" if kind == "text" else "application/json"
                            )
                        },
                    },
                }
                if kind != "static":
                    mapping["response"]["transformers"] = ["response-template"]
                (root / "mappings" / f"{case_id}.json").write_text(json.dumps(mapping))
    (root / "cases.json").write_text(json.dumps(cases, indent=2))
    return cases


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "fixtures")
