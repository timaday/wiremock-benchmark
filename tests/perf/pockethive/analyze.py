"""Verify PocketHive result bodies and independently retained WireMock captures."""

import argparse
import csv
import hashlib
import importlib.util
import json
import sqlite3
import zlib
from datetime import datetime
from pathlib import Path


def seconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def analyze(bundle, results, archive, metrics, canonical_repo):
    spec = importlib.util.spec_from_file_location('fixtures', canonical_repo / 'tools/fixtures.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    manifest = json.loads((bundle / 'benchmark.json').read_text())
    expected = {row['benchId']: row for path in (bundle / 'datasets').glob('*.csv')
                for row in csv.DictReader(path.open())}
    records = [json.loads(line) for line in results.open()]
    seen, valid, errors = set(), set(), []
    captures = {}
    with sqlite3.connect(f'file:{archive.resolve()}?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        for identifier, phase, size, digest, compressed in db.execute(
                'SELECT request_id,phase,body_bytes,body_sha256,payload_zlib FROM events WHERE run_id=?',
                (manifest['runId'],)):
            event = json.loads(zlib.decompress(compressed))
            captures.setdefault(identifier, {}).setdefault(phase, []).append(
                (size, digest, event['timestampMs'] / 1000))
    for record in records:
        identifier = record['bench_id']
        if identifier not in expected or identifier in seen:
            errors.append({'id': identifier, 'error': 'unexpected or duplicate result'})
            continue
        seen.add(identifier)
        row = expected[identifier]
        size = int(row['size'])
        empty = json.dumps({'id': identifier, 'padding': ''}, separators=(',', ':'))
        request = json.dumps({'id': identifier, 'padding': 'x' * (size - len(empty))}, separators=(',', ':'))
        response = fixtures.response(row['caseId'].split('-')[0], size, identifier)
        request_hash = hashlib.sha256(request.encode()).hexdigest()
        response_hash = hashlib.sha256(response.encode()).hexdigest()
        phases = captures.get(identifier, {})
        checks = {
            'status': record['status'] == 200 and record['outcome'] == 'http_response',
            'path': record['path'] == '/bench/' + row['caseId'],
            'request': record['request_sha256'] == request_hash,
            'response': record['response_sha256'] == response_hash,
            'capturePhases': set(phases) == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
                             and all(len(events) == 1 for events in phases.values()),
            'captureRequest': bool(phases.get('REQUEST')) and phases['REQUEST'][0][:2] == (size, request_hash),
            'captureResponse': bool(phases.get('RESPONSE_PREPARED')) and phases['RESPONSE_PREPARED'][0][:2] == (size, response_hash),
        }
        failed = [key for key, passed in checks.items() if not passed]
        if failed:
            errors.append({'id': identifier, 'failed': failed})
        else:
            valid.add(identifier)
    summary = {'runId': manifest['runId'], 'expected': len(expected), 'collected': len(records),
               'valid': len(valid), 'missing': len(set(expected) - seen),
               'unexpectedCaptureIds': len(set(captures) - set(expected)),
               'captureEvents': sum(len(events) for phases in captures.values() for events in phases.values()),
               'errors': errors[:20], 'errorCount': len(errors)}
    delivery = json.loads(metrics.read_text())
    summary['captureDelivery'] = delivery
    summary['integrityPassed'] = (len(valid) == len(expected) == len(records)
                                  and not summary['unexpectedCaptureIds']
                                  and delivery['enabled'] and delivery['brokerConnected']
                                  and delivery['errors'] == delivery['pending'] == 0
                                  and delivery['committed'] == delivery['confirmed'])
    if records:
        latencies = sorted((seconds(r['collected_at']) - seconds(r['offered_at'])) * 1000 for r in records)
        summary['pipelineLatencyMs'] = {name: latencies[min(len(latencies)-1, int(len(latencies)*p))]
                                        for name, p in [('p50', .5), ('p95', .95), ('p99', .99)]}
        headers = sorted(r['http_header_duration_ms'] for r in records)
        summary['httpHeaderLatencyMs'] = {name: headers[min(len(headers)-1, int(len(headers)*p))]
                                          for name, p in [('p50', .5), ('p95', .95), ('p99', .99)]}
        lanes = {}
        for record in records:
            lane = record['bench_id'][17:19]
            lanes.setdefault(lane, []).append(seconds(record['offered_at']))
        summary['laneArrivalSpansSeconds'] = {lane: max(times)-min(times) for lane, times in lanes.items()}
        duration = manifest['measurementSeconds']
        if duration:
            start = max(min(times) for times in lanes.values()) + manifest['warmupSeconds']
            end = start + duration
            inside = lambda timestamp: start <= timestamp < end
            summary['measurementStartEpoch'] = start
            summary['measurementSeconds'] = duration
            summary['lanesCoverWindow'] = len(lanes) == 4 and all(max(times) >= end for times in lanes.values())
            summary['observedOfferedRps'] = sum(inside(seconds(r['offered_at'])) for r in records) / duration
            summary['validCollectedRps'] = sum(r['bench_id'] in valid and inside(seconds(r['collected_at'])) for r in records) / duration
            for phase, key in [('REQUEST', 'serverReceivedRps'), ('SEND_COMPLETED', 'serverCompletedRps')]:
                summary[key] = sum(inside(event[2]) for phases in captures.values() for event in phases.get(phase, [])) / duration
            summary['ratePassed'] = (summary['lanesCoverWindow'] and summary['validCollectedRps'] >= 1000
                                     and summary['serverCompletedRps'] >= 1000)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['bundle', 'results', 'archive', 'metrics', 'canonical-repo', 'output']:
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    summary = analyze(args.bundle, args.results, args.archive, args.metrics, args.canonical_repo)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary['integrityPassed'] and summary.get('ratePassed', True) else 2)
