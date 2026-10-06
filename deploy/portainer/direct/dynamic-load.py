#!/usr/bin/env python3
"""Run the bounded local headless demonstration specified in gatling/DYNAMIC.md."""
import argparse
import base64
import csv
from functools import partial
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import urllib.request
import uuid
import zlib

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location('dedicated_smoke', HERE / 'dedicated-smoke.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
GIB = 1024 ** 3


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def host_sample(root):
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    pressure = Path('/proc/pressure/memory').read_text()
    full = float(pressure.split('full avg10=')[1].split()[0])
    return {'time': time.time(), 'availableBytes': int(memory['MemAvailable'].split()[0]) * 1024,
            'swapInPages': int(vm['pswpin']), 'swapOutPages': int(vm['pswpout']),
            'memoryFullAvg10': full, 'memoryPressure': pressure,
            'evidenceFreeBytes': shutil.disk_usage(root).free,
            'dockerFreeBytes': shutil.disk_usage('/var/lib/docker').free}


def guard(sample):
    assert sample['availableBytes'] >= 2 * GIB, 'Insufficient available memory'
    assert sample['evidenceFreeBytes'] >= 5 * GIB, 'Insufficient evidence storage'
    assert sample['dockerFreeBytes'] >= GIB, 'Insufficient Docker storage'
    assert sample['memoryFullAvg10'] <= 5, 'Sustained host memory pressure'


def reconcile(root, run, directory, delay_ms):
    expected = {}
    elapsed = []
    windows = [0] * 5
    start = int((directory / 'started-ms.txt').read_text()) + 45000
    failed = 0
    with (directory / 'clients.csv').open() as source:
        for row in csv.DictReader(source):
            assert row['id'] not in expected, 'Duplicate client ID'
            expected[row['id']] = (int(row['bytes']), row['requestSha256'], row['responseSha256'])
            failed += row['success'] != 'true'
            assert int(row['elapsedMs']) >= delay_ms - 2, 'Response arrived before configured delay'
            elapsed.append(int(row['elapsedMs']))
            window = (int(row['completedMs']) - start) // 60000
            if 0 <= window < 5 and row['success'] == 'true':
                windows[window] += 1
    count = len(expected)
    assert count > 0 and failed == 0, f'{failed} failed client requests'
    db_path = root / 'archive/events.db'

    def archived():
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
            return db.execute('SELECT count(*) FROM events WHERE run_id=?', (run,)).fetchone()[0] >= count * 3
    harness.wait_for(archived, 180)
    events = 0
    current = None
    phases = set()
    correlation = None
    with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
        for internal_id, phase, size, digest, compressed in db.execute(
                'SELECT request_id,phase,body_bytes,body_sha256,payload_zlib FROM events '
                'WHERE run_id=? ORDER BY request_id,phase', (run,)):
            event = json.loads(zlib.decompress(compressed))
            if current != internal_id:
                if current is not None:
                    assert phases == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
                    del expected[correlation]
                current, correlation, phases = internal_id, event['correlationId'], set()
            assert event['correlationId'] == correlation and correlation in expected
            assert event['schemaVersion'] == 2 and event['correlationStatus'] == 'PRESENT'
            assert event['requestId'] == internal_id and event['runId'] == run
            assert event['phase'] == phase and phase not in phases
            assert event['method'] == 'POST' and event['url'] == '/transaction'
            body = base64.b64decode(event['bodyBase64'], validate=True)
            assert size == len(body) and digest == hashlib.sha256(body).hexdigest()
            wanted = expected[correlation]
            if phase == 'REQUEST':
                assert (size, digest) == wanted[:2]
                assert not any(key.lower().startswith('x-bench-') for key in event['headers'])
            else:
                assert size == 0 and digest == wanted[2] and event['status'] == 200
            phases.add(phase)
            events += 1
        assert phases == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
        del expected[correlation]
    assert not expected and events == count * 3
    elapsed.sort()
    return {'requests': count, 'events': events, 'failedRequests': failed,
            'missingCaptures': 0, 'extraCaptures': 0, 'exactBodyHashesVerified': True,
            'successfulCompletionsPerSecondByHoldMinute': [value / 60 for value in windows],
            'latencyMs': {'p50': elapsed[int(len(elapsed) * .5)],
                          'p95': elapsed[int(len(elapsed) * .95)],
                          'p99': elapsed[int(len(elapsed) * .99)], 'max': elapsed[-1]}}


def exercise(runtime, root, docker, api, mock_url, env, *, delay_ms):
    queue = env['CAPTURE_PREFIX'] + '.' + runtime
    harness.wait_for(lambda: api('queues/%2F/' + queue).get('consumers') == 1)
    containers = docker('ps', '-aq').splitlines()
    metrics_url = 'http://' + docker('port', runtime, '8081') + '/metrics'

    def states():
        data = json.loads(subprocess.check_output(['docker', 'inspect', *containers], text=True))
        return [{'name': x['Name'], 'image': x['Image'], 'restarts': x['RestartCount'],
                 'state': x['State']} for x in data]

    save(root / 'initial-state.json', states())
    guard(host_sample(root))
    mapping = json.loads((HERE / 'empty-200-mapping.json').read_text())
    mapping['response']['fixedDelayMilliseconds'] = delay_ms
    reports = []
    for label, field, rate, ramp, steady in [('smoke', 'correlationId', 10, 0, 10),
                                             ('hold', 'requestId', 1020, 15, 330)]:
        directory = root / label
        directory.mkdir()
        run = 'dynamic-' + label + '-' + uuid.uuid4().hex
        mapping['response']['transformerParameters']['capture'].update(
            runId=run, correlationJsonPath='$.' + field)
        method = 'POST' if label == 'smoke' else 'PUT'
        path = '/__admin/mappings' + ('' if label == 'smoke' else '/' + mapping['id'])
        request = urllib.request.Request(mock_url + path, data=json.dumps(mapping).encode(),
                    headers={'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status in (200, 201)
        save(directory / 'mapping.json', mapping)
        params = dict(output=str(directory), run=run, field=field, rate=rate,
                      ramp=ramp, steady=steady, url=mock_url, delayMs=delay_ms)
        save(directory / 'parameters.json', params)
        command = ['java', '-Xms128m', '-Xmx768m', '-XX:ActiveProcessorCount=4',
                   '-Dlogback.configurationFile=' + str(REPO / 'tests/perf/gatling/src/main/resources/logback.xml'),
                   '--add-opens=java.base/java.lang=ALL-UNNAMED',
                   '--add-opens=java.base/jdk.internal.misc=ALL-UNNAMED',
                   '-Xlog:gc:file=' + str(directory / 'gc.log') + ':time,level,tags',
                   *['-Ddemo.' + key + '=' + str(value) for key, value in params.items()],
                   '-cp', str(REPO / 'tests/perf/gatling/target/dynamic-classes') + ':'
                   + str(REPO / 'tests/perf/gatling/target/dependency/*'),
                   'io.gatling.app.Gatling', '-s', 'bench.load.DynamicCaptureSimulation',
                   '-nr', '-rf', str(directory / 'gatling')]
        print('Starting ' + label + ': ' + str(rate) + '/s', flush=True)
        samples = []
        with (directory / 'gatling.log').open('w') as log, (directory / 'samples.jsonl').open('w') as capture:
            process = subprocess.Popen(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    sample = host_sample(root)
                    sample['containers'] = [json.loads(line) for line in subprocess.check_output(
                        ['docker', 'stats', '--no-stream', '--format', '{{json .}}', *containers], text=True).splitlines()]
                    q = api('queues/%2F/' + queue)
                    sample['queue'] = {key: q.get(key) for key in ('messages', 'messages_ready',
                                        'messages_unacknowledged', 'consumers', 'message_stats')}
                    with urllib.request.urlopen(metrics_url, timeout=10) as response:
                        sample['metrics'] = response.read().decode()
                    capture.write(json.dumps(sample) + '\n')
                    capture.flush()
                    samples.append(sample)
                    guard(sample)
                    if len(samples) % 6 == 1:
                        print(json.dumps({'phase': label, 'availableGiB': round(sample['availableBytes'] / GIB, 2),
                                          'queueMessages': q.get('messages'), 'elapsedSamples': len(samples)}), flush=True)
                    time.sleep(8)
                assert process.returncode == 0, 'Gatling failed: see gatling.log'
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=35)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        report = reconcile(root, run, directory, delay_ms)
        report.update(runId=run, phase=label, offeredRate=rate, field=field,
                      minimumAvailableGiB=min(x['availableBytes'] for x in samples) / GIB,
                      swapInPages=samples[-1]['swapInPages'] - samples[0]['swapInPages'],
                      swapOutPages=samples[-1]['swapOutPages'] - samples[0]['swapOutPages'],
                      maximumQueueMessages=max(x['queue']['messages'] or 0 for x in samples))
        save(directory / 'verification.json', report)
        print(json.dumps(report), flush=True)
        if label == 'hold':
            assert min(report['successfulCompletionsPerSecondByHoldMinute']) >= 1000, 'Throughput below target'
        reports.append(report)
    harness.wait_for(lambda: api('queues/%2F/' + queue).get('messages') == 0)
    with urllib.request.urlopen(metrics_url, timeout=10) as response:
        metrics = json.load(response)
    save(root / 'final-metrics.json', metrics)
    assert metrics['pending'] == 0 and metrics['errors'] == 0 and metrics['reconnects'] == 0
    assert metrics['committed'] == metrics['confirmed'] == sum(r['events'] for r in reports)
    with urllib.request.urlopen(metrics_url.replace('/metrics', '/prometheus'), timeout=10) as response:
        (root / 'final-prometheus.txt').write_bytes(response.read())
    final = states()
    save(root / 'final-state.json', final)
    assert all(x['restarts'] == 0 and x['state']['Running'] and not x['state']['OOMKilled'] for x in final)
    result = {'passed': True, 'runtime': runtime, 'delayMs': delay_ms, 'holdSeconds': 300,
              'noRestartsOrOOM': True, 'finalQueueMessages': 0, 'phases': reports}
    save(root / 'verification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delay-ms', type=int, choices=(1000, 6000), default=1000)
    args = parser.parse_args()
    images = json.loads((REPO / 'target/direct-image/images.json').read_text())
    for item in images.values():
        actual = subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{.Id}}', item['tag']], text=True).strip()
        assert actual == item['id'], 'Image identity changed'
    target = REPO / 'tests/perf/gatling/target/dynamic-classes'
    target.mkdir(exist_ok=True)
    shutil.copyfile(REPO / 'tests/perf/gatling/src/main/resources/logback.xml', target / 'logback.xml')
    subprocess.run(['javac', '--release', '21', '-cp', str(REPO / 'tests/perf/gatling/target/dependency/*'),
                    '-d', str(target), *map(str, (REPO / 'tests/perf/gatling/src/main/java').rglob('*.java'))], check=True)
    settings = {'HEADLESS_DIRECT_IMAGE': images['headless']['tag'],
                'ARCHIVE_IMAGE': images['archive']['tag'], 'CAPTURE_IDENTITY_MODE': 'STUB_JSON'}
    root = args.output.resolve()
    guard(host_sample(root.parent))
    result = harness.trial('headless', root, exercise=partial(exercise, delay_ms=args.delay_ms),
                           settings=settings, publish_metrics=True)
    print(json.dumps(result), flush=True)
