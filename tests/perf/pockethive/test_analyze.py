"""Mutation checks against a completed smoke run: bundle results archive metrics canonical-repo."""

import json
import sys
import tempfile
from pathlib import Path

from analyze import analyze


def check(bundle, results, archive, metrics, canonical_repo):
    baseline = analyze(bundle, results, archive, metrics, canonical_repo)
    assert baseline['integrityPassed'], 'The supplied smoke evidence must pass before mutation'
    rows = [json.loads(line) for line in results.open()]
    with tempfile.TemporaryDirectory() as directory:
        changed_results = Path(directory) / 'results.jsonl'
        changed_metrics = Path(directory) / 'metrics.json'
        for fault in ['missing', 'duplicate', 'corrupt', 'http-error', 'undrained']:
            altered = [dict(row) for row in rows]
            delivery = json.loads(metrics.read_text())
            if fault == 'missing':
                altered.pop()
            elif fault == 'duplicate':
                altered.append(altered[0])
            elif fault == 'corrupt':
                altered[0]['response_sha256'] = '0' * 64
            elif fault == 'http-error':
                altered[0]['status'] = 500
            elif fault == 'undrained':
                delivery['pending'] = 1
            changed_results.write_text(''.join(json.dumps(row) + '\n' for row in altered))
            changed_metrics.write_text(json.dumps(delivery))
            verdict = analyze(bundle, changed_results, archive, changed_metrics, canonical_repo)
            assert not verdict['integrityPassed'], fault + ' was incorrectly accepted'
            print(fault + ': rejected')


if __name__ == '__main__':
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    check(*(Path(value) for value in sys.argv[1:]))
