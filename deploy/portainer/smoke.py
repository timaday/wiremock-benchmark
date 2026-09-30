"""Check all twelve six-second cases against each published mock HTTP endpoint."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import fixtures


def check(base, runtime):
    run_id = secrets.token_hex(8)
    cases = [(size, kind) for size in fixtures.SIZES for kind in fixtures.TEMPLATES]
    def request(index_case):
        index, (size, kind) = index_case
        identifier = f'{run_id}-00{index:010d}'
        empty = json.dumps({'id': identifier, 'padding': ''}, separators=(',', ':'))
        body = json.dumps({'id': identifier, 'padding': 'x' * (size-len(empty))}, separators=(',', ':')).encode()
        case_id = f'{kind}-{size}-6000'
        req = urllib.request.Request(base.rstrip('/') + '/bench/' + case_id, data=body,
            headers={'X-Bench-Run': run_id, 'X-Bench-Id': identifier, 'Content-Type': 'application/json'})
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as response:
            actual = response.read(); status = response.status
        elapsed = time.monotonic()-started
        assert status == 200 and elapsed >= 5.998
        assert actual == fixtures.response(kind, size, identifier).encode(), case_id
        return {'id': identifier, 'case': case_id, 'size': size, 'elapsedSeconds': elapsed,
                'requestSha256': hashlib.sha256(body).hexdigest(), 'responseSha256': hashlib.sha256(actual).hexdigest()}
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(request, enumerate(cases)))
    return {'runtime': runtime, 'runId': run_id, 'requests': records}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--official-url', required=True)
    p.add_argument('--headless-url', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    results = [check(args.official_url, 'official'), check(args.headless_url, 'headless')]
    args.output.write_text(json.dumps(results, indent=2) + '\n')
    print('PASS: 24 exact request/response cases, both runtimes, six-second minimum delay')
