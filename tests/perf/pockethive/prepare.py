"""Prepare finite PocketHive workloads from wiremock-benchmark's canonical catalogue."""

import argparse
import csv
import importlib.util
import json
import secrets
from pathlib import Path


def artemis_input():
    return {'type': 'ARTEMIS', 'artemis': {'consumerWindowBytes': 1048576}}


def artemis_output():
    return {'type': 'ARTEMIS', 'artemis': {'persistent': True}}


def evidence_output(run_id):
    return {'type': 'REDIS', 'redis': {
        'host': 'wmb-ph-results', 'port': 6379, 'sourceStep': 'LAST',
        'pushDirection': 'RPUSH', 'routes': [], 'targetListTemplate': '',
        'defaultList': 'wmb.' + run_id, 'maxLen': -1, 'ssl': False,
    }}


def body_template(sizes, id_length, identifier):
    overhead = len('{"id":"' + '0' * id_length + '","padding":""}')
    branches = []
    for index, size in enumerate(sizes):
        directive = 'if' if index == 0 else 'elseif'
        branches.append('{% ' + directive + " payloadAsJson.size == '" + str(size) + "' %}" + 'x' * (size - overhead))
    return '{"id":"' + identifier + '","padding":"' + ''.join(branches) + '{% endif %}"}'


def result_template():
    # Keep the actual response map before selecting the recorded HTTP request step.
    # eval sees the current Pebble payload variable; it cannot access arbitrary Java methods.
    return ''.join([
        '{% set result = payload %}',
        '{% set payload = workItem.steps[1].payload %}',
        '{"bench_id":"{{ eval("#json_path(payload, \'/request/headers/X-Bench-Id\')") }}",',
        '"offered_at":"{{ eval("#json_path(payload, \'/request/headers/X-Bench-Offered-At\')") }}",',
        '"request_sha256":"{{ eval("#sha256_hex(#json_path(payload, \'/request/body\'))") }}",',
        '{% set payload = result %}',
        '"response_sha256":"{{ eval("#sha256_hex(#json_path(payload, \'/outcome/body\'))") }}",',
        '"status":{{ result.outcome.status }},',
        '"outcome":"{{ result.outcome.type }}",',
        '"path":"{{ result.request.path }}",',
        '"http_header_duration_ms":{{ result.metrics.durationMs }},',
        '"processor_pacing_ms":{{ result.metrics.connectionLatencyMs }},',
        '"hops":[{% for hop in workItem.observabilityContext.get.hops %}',
        '{"service":"{{ hop.service }}","received_at":"{{ hop.receivedAt }}",',
        '"processed_at":{% if hop.processedAt is null %}null{% else %}"{{ hop.processedAt }}"{% endif %}}',
        '{% if not loop.last %},{% endif %}{% endfor %}],',
        '"collected_at":"{{ eval("nowIso") }}"}',
    ])


def prepare(canonical_repo, output, runtime, mode):
    spec = importlib.util.spec_from_file_location('canonical_fixtures', canonical_repo / 'tools/fixtures.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixture_root = output / 'fixtures'
    cases = [case for case in fixtures.generate(fixture_root) if case['delay'] == 6000]
    run_id = secrets.token_hex(8)
    scenario_id = f'ph-wiremock-{runtime}-{mode}-{run_id[:8]}'
    bundle = output / 'bundles' / scenario_id
    (bundle / 'datasets').mkdir(parents=True)
    rate, rows, warmup, measurement = {
        'smoke': (1, 12, 20, 0),
        'load': (255, 22950, 20, 60),
        'diagnostic': (255, 255 * 270, 60, 180),
        'endurance': (255, 255 * 3690, 60, 3600),
    }[mode]
    bees, edges = [], []
    for lane in range(4):
        gen, proc = f'generator-{lane}', f'processor-{lane}'
        queue = f'requests-{lane}'
        dataset = 'shared.csv' if mode == 'endurance' else f'lane-{lane}.csv'
        if mode != 'endurance' or lane == 0:
            with (bundle / 'datasets' / dataset).open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['sequence' if mode == 'endurance' else 'benchId', 'caseId', 'size'])
                for seq in range(rows):
                    case = cases[seq % len(cases)]
                    bench_id = f'{run_id}-{lane:02d}{seq:010d}'
                    assert len(bench_id) == fixtures.ID_LENGTH
                    writer.writerow([f'{seq:010d}' if mode == 'endurance' else bench_id, case['id'], case['size']])
        identifier = (f'{run_id}-{lane:02d}' + '{{ payloadAsJson.sequence }}'
                      if mode == 'endurance' else '{{ payloadAsJson.benchId }}')
        bees.extend([
            {
                'role': gen, 'image': 'generator:latest',
                'env': {'JAVA_TOOL_OPTIONS': '-Xms128m -Xmx512m'},
                'work': {'out': {'out': queue}},
                'ports': [{'id': 'out', 'direction': 'out'}],
                'config': {
                    'historyPolicy': 'FULL',
                    'inputs': {'type': 'CSV_DATASET', 'csv': {
                        'filePath': f'/app/scenario/datasets/{dataset}',
                        'ratePerSec': rate, 'rotate': False, 'skipHeader': True,
                        'delimiter': ',', 'charset': 'UTF-8',
                        'startupDelaySeconds': 10, 'tickIntervalMs': 100,
                    }},
                    'outputs': artemis_output(),
                    'message': {
                        'bodyType': 'HTTP', 'method': 'POST',
                        'path': '/bench/{{ payloadAsJson.caseId }}',
                        'body': body_template(fixtures.SIZES, fixtures.ID_LENGTH, identifier),
                        'headers': {
                            'Content-Type': 'application/json',
                            'X-Bench-Run': run_id,
                            'X-Bench-Id': identifier,
                            'X-Bench-Offered-At': '{{ eval("nowIso") }}',
                        },
                    },
                },
            },
            {
                'role': proc, 'image': 'processor:latest',
                'env': {'JAVA_TOOL_OPTIONS': '-Xms256m -Xmx1g -Xss256k'},
                'work': {'in': {'in': queue}, 'out': {'out': 'results'}},
                'ports': [{'id': 'in', 'direction': 'in'}, {'id': 'out', 'direction': 'out'}],
                'config': {
                    'baseUrl': "{{ sut.endpoints['default'].baseUrl }}",
                    'mode': 'RATE_PER_SEC', 'ratePerSec': rate,
                    'threadCount': 16 if mode == 'smoke' else 1800,
                    'connectionReuse': 'PER_THREAD', 'keepAlive': True,
                    'timeoutMs': 30000, 'sslVerify': True, 'historyPolicy': 'FULL',
                    'inputs': artemis_input(),
                    'outputs': artemis_output(),
                },
            },
        ])
        edges.extend([
            {'id': f'request-{lane}', 'from': {'role': gen, 'port': 'out'}, 'to': {'role': proc, 'port': 'in'}},
            {'id': f'result-{lane}', 'from': {'role': proc, 'port': 'out'}, 'to': {'role': 'evidence', 'port': 'in'}},
        ])
    bees.extend([
        {
            'role': 'evidence', 'image': 'moderator:latest',
            'env': {'JAVA_TOOL_OPTIONS': '-Xms128m -Xmx768m'},
            'work': {'in': {'in': 'results'}},
            'ports': [{'id': 'in', 'direction': 'in'}],
            'config': {
                'mode': {'type': 'pass-through', 'ratePerSec': 0},
                'inputs': artemis_input(), 'outputs': evidence_output(run_id),
                'historyPolicy': 'LATEST_ONLY',
                'interceptors': {'templating': {'template': result_template()}},
            },
        },
    ])
    scenario = {
        'protocolVersion': '2.0.0', 'id': scenario_id,
        'name': f'WireMock {runtime}: PocketHive {mode}',
        'description': f'Finite six-second benchmark: {4 * rate} offered requests/s; {4 * rows} unique requests.',
        'template': {'image': 'swarm-controller:latest', 'bees': bees},
        'topology': {'version': 1, 'edges': edges},
    }
    (bundle / 'scenario.yaml').write_text(json.dumps(scenario, indent=2) + '\n')
    sut = bundle / 'sut' / runtime
    sut.mkdir(parents=True)
    (sut / 'sut.yaml').write_text(json.dumps({
        'id': runtime, 'name': f'Isolated benchmark WireMock {runtime}', 'type': 'http',
        'endpoints': {'default': {'kind': 'http', 'baseUrl': f'http://wmb-ph-{runtime}:8080'}},
    }, indent=2) + '\n')
    manifest = {
        'runId': run_id, 'scenarioId': scenario_id, 'runtime': runtime, 'mode': mode,
        'offeredRate': rate * 4, 'expectedRequests': rows * 4,
        'warmupSeconds': warmup, 'measurementSeconds': measurement,
        'cases': [{key: case[key] for key in ['id', 'size', 'delay', 'template']} for case in cases],
    }
    (bundle / 'benchmark.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return bundle


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--runtime', required=True, choices=['official', 'headless'])
    parser.add_argument('--mode', required=True, choices=['smoke', 'load', 'diagnostic', 'endurance'])
    args = parser.parse_args()
    print(prepare(args.canonical_repo, args.output, args.runtime, args.mode))
