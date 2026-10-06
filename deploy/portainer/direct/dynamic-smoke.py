#!/usr/bin/env python3
"""Verify live body-correlation configuration through published WireMock HTTP APIs.

Uses the dedicated-stack test harness and real persistent RabbitMQ/archive.
Retains its test containers and evidence; does not publish or deploy images.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dedicated_smoke', HERE / 'dedicated-smoke.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def exercise(runtime, root, docker, api, mock_url, env):
    if runtime == 'headless':
        test_env = dict(env)
        test_env['CAPTURE_TEST_RABBIT_URI'] = ('amqp://benchmark:' + env['RABBIT_PASSWORD']
            + '@' + docker('port', 'rabbit', '5672') + '/%2f')
        with (root / 'maven-tests.log').open('w') as output:
            subprocess.run(['mvn', '-B', '-ntp', '-Dbenchmark.build.directory=target/direct-maven', 'test'],
                           cwd=HERE.parents[2], env=test_env, stdout=output, stderr=subprocess.STDOUT, check=True)

    def http(method, path, value, raw=False):
        data = value if raw else json.dumps(value).encode()
        request = urllib.request.Request(mock_url + path, data=data, method=method,
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    run_id = 'dynamic-' + uuid.uuid4().hex
    mapping = {'id': str(uuid.uuid4()), 'request': {'method': 'POST', 'urlPath': '/transaction'},
               'response': {'status': 200, 'fixedDelayMilliseconds': 1000,
                            'transformerParameters': {'capture': {'runId': run_id,
                                'correlationJsonPath': '$.correlationId',
                                'missingCorrelation': 'RECORD_UNCORRELATED'}}}}
    code, _ = http('POST', '/__admin/mappings', mapping)
    assert code == 201, code
    expected = []

    def send(body, correlation, state='PRESENT', response=b''):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        started = time.monotonic()
        code, received = http('POST', '/transaction', raw, raw=True)
        assert code == 200 and received == response, (code, received)
        elapsed = time.monotonic() - started
        assert elapsed >= .998, elapsed
        item = {'requestBodyBase64': base64.b64encode(raw).decode(),
                'responseBodyBase64': base64.b64encode(received).decode(),
                'correlationId': correlation, 'correlationStatus': state, 'elapsedSeconds': elapsed}
        expected.append(item)
        return item

    def archived():
        try:
            with sqlite3.connect(f'file:{root / "archive/events.db"}?mode=ro', uri=True) as db:
                rows = db.execute('SELECT payload_zlib FROM events WHERE run_id=?', (run_id,)).fetchall()
            return [json.loads(zlib.decompress(row[0])) for row in rows]
        except sqlite3.OperationalError:
            return []

    send({'correlationId': 'first'}, 'first')
    send({}, '', 'MISSING')
    send({'correlationId': None}, '', 'MISSING')
    send(b'{not-json', '', 'INVALID_BODY')
    send({'correlationId': 42}, '', 'INVALID_VALUE')

    # Start an HTTP request under the old mapping, observe its captured REQUEST,
    # then edit the mapping while its delayed response remains in flight.
    mapping['response']['fixedDelayMilliseconds'] = 3000
    assert http('PUT', '/__admin/mappings/' + mapping['id'], mapping)[0] == 200
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(send, {'correlationId': 'in-flight-old', 'requestId': 'in-flight-new'}, 'in-flight-old')
        harness.wait_for(lambda: any(x['phase'] == 'REQUEST' and x['correlationId'] == 'in-flight-old' for x in archived()))
        assert not pending.done(), 'The in-flight edit must precede client completion'
        mapping['response']['transformerParameters']['capture']['correlationJsonPath'] = '$.requestId'
        mapping['response']['fixedDelayMilliseconds'] = 1000
        assert http('PUT', '/__admin/mappings/' + mapping['id'], mapping)[0] == 200
        pending.result()

    send({'correlationId': 'ignored', 'requestId': 'second'}, 'second')
    send({'correlationId': 'must-not-be-used'}, '', 'MISSING')
    send({'requestId': 'duplicate'}, 'duplicate')
    send({'requestId': 'duplicate'}, 'duplicate')

    invalid = json.loads(json.dumps(mapping))
    invalid['response']['transformerParameters']['capture']['correlationJsonPath'] = '$['
    code, _ = http('PUT', '/__admin/mappings/' + mapping['id'], invalid)
    assert 400 <= code < 500, code
    send({'requestId': 'after-invalid-edit'}, 'after-invalid-edit')

    # Response templating may use the same selector, but is not needed above.
    mapping['response']['transformers'] = ['response-template']
    mapping['response']['jsonBody'] = {'message': "Accepted {{jsonPath request.body parameters.capture.correlationJsonPath}}"}
    assert http('PUT', '/__admin/mappings/' + mapping['id'], mapping)[0] == 200
    raw = json.dumps({'requestId': 'templated'}).encode()
    code, rendered = http('POST', '/transaction', raw, raw=True)
    assert code == 200 and json.loads(rendered) == {'message': 'Accepted templated'}
    expected.append({'requestBodyBase64': base64.b64encode(raw).decode(),
                     'responseBodyBase64': base64.b64encode(rendered).decode(),
                     'correlationId': 'templated', 'correlationStatus': 'PRESENT'})

    # Oversize and unselected traffic must not enter this run's capture set.
    assert http('POST', '/transaction', b'x' * 65537, raw=True)[0] == 413
    assert http('POST', '/not-selected', b'{}', raw=True)[0] == 404
    harness.wait_for(lambda: len(archived()) == len(expected) * 3)
    events = archived()
    groups = {}
    for event in events:
        assert event['schemaVersion'] == 2
        groups.setdefault(event['requestId'], {})[event['phase']] = event
    assert len(groups) == len(expected)
    remaining = list(expected)
    for request_id, phases in groups.items():
        uuid.UUID(request_id)
        assert set(phases) == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
        request, response = phases['REQUEST'], phases['RESPONSE_PREPARED']
        match = next(x for x in remaining if x['requestBodyBase64'] == request['bodyBase64'])
        remaining.remove(match)
        assert response['bodyBase64'] == match['responseBodyBase64'] and response['status'] == 200
        assert phases['SEND_COMPLETED']['bodyBase64'] == ''
        for event in phases.values():
            assert event['correlationId'] == match['correlationId']
            assert event['correlationStatus'] == match['correlationStatus']
            assert event['eventId'].startswith(request_id + ':')
    assert not remaining
    queue = env['CAPTURE_PREFIX'] + '.' + runtime
    harness.wait_for(lambda: api('queues/%2F/' + queue).get('messages') == 0)
    container = docker('ps', '-q', runtime)
    inspection = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
    assert inspection['RestartCount'] == 0 and inspection['State']['Running']
    (root / 'client-results.json').write_text(json.dumps(expected, indent=2) + '\n')
    (root / 'captured-events.json').write_text(json.dumps(events, indent=2) + '\n')
    result = {'runtime': runtime, 'requestsReconciled': len(expected), 'eventsReconciled': len(events),
              'emptyResponsesVerified': 11, 'liveFieldChange': True, 'invalidEditRejected': True,
              'missingAndInvalidCorrelationCaptured': True, 'duplicateIdsRemainDistinct': True,
              'oversizeRejected': True, 'restarts': 0, 'passed': True}
    (root / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True, help='Matching build.py images.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    images = json.loads(args.images.read_text())
    settings = {key.upper() + '_DIRECT_IMAGE': images[key]['tag'] for key in ('headless', 'official')}
    settings.update(ARCHIVE_IMAGE=images['archive']['tag'], CAPTURE_IDENTITY_MODE='STUB_JSON')
    args.output = args.output.resolve()
    args.output.mkdir(exist_ok=False)
    results = []
    for runtime in ('headless', 'official'):
        print('Testing dynamic correlation: ' + runtime, flush=True)
        results.append(harness.trial(runtime, args.output / runtime, exercise, settings, publish_amqp=True))
        print(json.dumps(results[-1]), flush=True)
    (args.output / 'verification.json').write_text(json.dumps(results, indent=2) + '\n')
