#!/usr/bin/env python3
"""Diagnose fresh PocketHive records using existing processor-hop timestamps.

Responsibility: distinguish queue/evidence delay from processor completion.
Must not: substitute for body/archive reconciliation or relabel legacy evidence timestamps.
Contract: tests/perf/pockethive/README.md, diagnostic timing.
"""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import json
from pathlib import Path

PROCESSORS = {f'processor-{lane}' for lane in range(4)}


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def records(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def stages(record):
    hops = [hop for hop in record['hops'] if hop['service'] in PROCESSORS]
    if len(hops) != 1 or not hops[0]['processed_at']:
        raise ValueError('Exactly one completed processor hop is required')
    offered = epoch(record['offered_at'])
    received = epoch(hops[0]['received_at'])
    completed = epoch(hops[0]['processed_at'])
    collected = epoch(record['collected_at'])
    if not offered <= received <= completed <= collected:
        raise ValueError('Non-monotonic stage timestamps; check clocks and hop ownership')
    return completed, collected, {
        'beforeProcessorMs': round((received - offered) * 1000),
        'processorMs': round((completed - received) * 1000),
        'afterProcessorMs': round((collected - completed) * 1000),
        'httpHeaderMs': record['http_header_duration_ms'],
        'processorPacingMs': record['processor_pacing_ms'],
    }


def distribution(histogram):
    total = sum(histogram.values())
    def quantile(fraction):
        seen = 0
        for value, count in sorted(histogram.items()):
            seen += count
            if seen >= max(1, total * fraction):
                return value
    return {'count': total, 'p50': quantile(.5), 'p99': quantile(.99), 'max': max(histogram)}


def analyze(bundle, result_path):
    manifest = json.loads((bundle / 'benchmark.json').read_text())
    first = {}
    for record in records(result_path):
        lane = record['bench_id'][17:19]
        if lane not in {'00', '01', '02', '03'}:
            raise ValueError('Unknown benchmark lane')
        t = epoch(record['offered_at'])
        first[lane] = min(first.get(lane, t), t)
    if len(first) != 4:
        raise ValueError('Four offered lanes are required')
    start = max(first.values()) + manifest['warmupSeconds']
    seconds = manifest['measurementSeconds']
    if seconds <= 0:
        raise ValueError('A positive measurement window is required')
    end = start + seconds
    histograms = {}
    completed_count = collected_count = count = 0
    minute_counts = Counter()
    for record in records(result_path):
        completed, collected, measurements = stages(record)
        count += 1
        for name, value in measurements.items():
            histograms.setdefault(name, Counter())[value] += 1
        if start <= completed < end:
            completed_count += 1
            minute_counts[int((completed - start) // 60)] += 1
        collected_count += int(start <= collected < end)
    return {
        'runId': manifest['runId'], 'records': count,
        'measurementStart': start, 'measurementEnd': end,
        'processorCompletionRps': completed_count / seconds,
        'evidenceStageRps': collected_count / seconds,
        'processorCompletionMinuteCounts': {
            str(i): minute_counts[i] for i in range((seconds + 59) // 60)},
        'stageDurationsMs': {k: distribution(v) for k, v in histograms.items()},
        'scope': 'Processor completion includes body read and result construction; not archive integrity or exact socket completion.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = analyze(args.bundle, args.results)
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps(report, indent=2))
