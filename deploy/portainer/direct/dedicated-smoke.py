#!/usr/bin/env python3
"""Exercise generated dedicated stacks locally; retain containers and full evidence.

Uses a bridge instead of Swarm placement, loopback published ports, fresh local
storage and the pinned images. Does not deploy to AWS or qualify throughput.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

import yaml

PORTAINER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PORTAINER))
from smoke import check
from yaml_format import stack_yaml


def wait_for(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, urllib.error.URLError, sqlite3.OperationalError):
            pass
        time.sleep(1)
    raise AssertionError('Timed out waiting for test postcondition')


def verify_archive(path, run):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT request_id,phase,body_bytes,body_sha256,payload_zlib '
                          'FROM events WHERE run_id=?', (run['runId'],)).fetchall()
    if len(rows) != len(run['requests']) * 3:
        return False
    for request in run['requests']:
        phases = {r[1]: r for r in rows if r[0] == request['id']}
        assert set(phases) == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
        for phase, key in [('REQUEST', 'requestSha256'), ('RESPONSE_PREPARED', 'responseSha256')]:
            row = phases[phase]
            event = json.loads(zlib.decompress(row[4]))
            assert event['runId'] == run['runId'] and event['requestId'] == request['id']
            body = base64.b64decode(event['bodyBase64'])
            assert row[2] == len(body) == request['size']
            assert row[3] == hashlib.sha256(body).hexdigest() == request[key]
    return True


def trial(runtime, root, exercise=None, settings=None, publish_amqp=False, publish_metrics=False):
    root.mkdir()
    (root / 'rabbit').mkdir()
    (root / 'archive').mkdir()
    env = dict(os.environ)
    for line in (PORTAINER / 'example-direct-rabbit.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            env[key] = value
    password = secrets.token_hex(24)
    env.update(RABBIT_PASSWORD=password, RABBIT_DATA_DIR=str(root / 'rabbit'),
               ARCHIVE_DATA_DIR=str(root / 'archive'))
    if settings is not None:
        env.update(settings)
    config = yaml.safe_load((PORTAINER / f'stack-direct-{runtime}-rabbit.yml').read_text())
    # Explicit local-test substitutions do not alter the published stack files.
    if settings is not None:
        if runtime.upper() + '_DIRECT_IMAGE' in settings:
            config['services'][runtime]['image'] = settings[runtime.upper() + '_DIRECT_IMAGE']
        if 'ARCHIVE_IMAGE' in settings:
            config['services']['archive']['image'] = settings['ARCHIVE_IMAGE']
    if publish_amqp:
        config['services']['rabbit']['ports'].append({'target': 5672, 'protocol': 'tcp', 'mode': 'ingress'})
    if publish_metrics:
        config['services'][runtime]['ports'].append({'target': 8081, 'protocol': 'tcp', 'mode': 'ingress'})
    config['networks']['capture'] = {'driver': 'bridge'}
    for service in config['services'].values():
        limits = service.pop('deploy')['resources']['limits']
        service.update(cpus=limits['cpus'], mem_limit=limits['memory'])
        for port in service.get('ports', []):
            port.update(published=0, host_ip='127.0.0.1')
            port.pop('mode')
    compose = root / 'compose.yml'
    compose.write_text(stack_yaml(config))
    project = 'direct-dedicated-' + runtime + '-' + secrets.token_hex(4)
    command = ['docker', 'compose', '-p', project, '-f', str(compose)]

    def docker(*args):
        result = subprocess.run([*command, *args], env=env, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(password, '[REDACTED]'))
        return result.stdout.strip()

    def endpoint(service, port):
        return 'http://' + docker('port', service, str(port))

    def api(path, body=None):
        headers = {'Authorization': 'Basic ' + base64.b64encode(('benchmark:' + password).encode()).decode()}
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(endpoint('rabbit', 15672) + '/api/' + path,
                                         data=data, headers=headers, method='GET' if body is None else 'PUT')
        request.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
        return json.loads(raw) if raw else True

    try:
        docker('up', '-d', '--pull', 'never', 'rabbit')
        wait_for(lambda: api('overview'))
        policies = api('policies/%2F')
        policy = next(p for p in policies if p['name'] == 'capture-bounds')
        assert policy['definition'] == {'max-length': 200000, 'max-length-bytes': 1073741824,
                                         'overflow': 'reject-publish'}
        docker('up', '-d', '--pull', 'never', runtime, 'archive')
        mock_url = endpoint(runtime, 8080)
        def ready():
            with urllib.request.urlopen(mock_url + '/__admin/health', timeout=3) as response:
                return response.status == 200
        wait_for(ready)
        if exercise is not None:
            return exercise(runtime, root, docker, api, mock_url, env)
        queue = env['CAPTURE_PREFIX'] + '.' + runtime
        wait_for(lambda: api('queues/%2F/' + queue).get('consumers') == 1)
        run = check(mock_url, runtime)
        (root / 'clients.json').write_text(json.dumps(run, indent=2) + '\n')
        wait_for(lambda: verify_archive(root / 'archive/events.db', run))

        # Queue persistent captures while the consumer is stopped, restart only
        # this test's broker, then reconcile the recovered records into SQLite.
        docker('stop', 'archive')
        retained = check(mock_url, runtime)
        (root / 'restart-clients.json').write_text(json.dumps(retained, indent=2) + '\n')
        wait_for(lambda: api('queues/%2F/' + queue).get('messages_ready') == 36)
        docker('restart', 'rabbit')
        wait_for(lambda: api('queues/%2F/' + queue).get('messages_ready') == 36)
        docker('start', 'archive')
        wait_for(lambda: verify_archive(root / 'archive/events.db', retained))
        wait_for(lambda: api('queues/%2F/' + queue).get('messages') == 0)

        # A fresh mock connection is needed after a broker restart. No successful
        # recovery claim is inferred from the previous process staying alive.
        docker('restart', runtime)
        mock_url = endpoint(runtime, 8080)
        wait_for(ready)
        docker('stop', 'archive')
        api('policies/%2F/capture-bounds', {'pattern': '.*', 'apply-to': 'queues', 'priority': 100,
             'definition': {'max-length': 1, 'max-length-bytes': 1073741824, 'overflow': 'reject-publish'}})
        body = b'x' * 1024
        request = urllib.request.Request(mock_url + '/bench/static-1024-6000', data=body,
            headers={'X-Bench-Run': 'overflow', 'X-Bench-Id': 'overflow-1'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response.read()
        except (OSError, urllib.error.URLError):
            pass
        container = docker('ps', '-aq', runtime)
        def failed_closed():
            state = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]['State']
            return not state['Running'] and state['ExitCode'] == 70
        wait_for(failed_closed, 30)
        wait_for(lambda: api('queues/%2F/' + queue).get('messages_ready') == 1)
        overflow_queue = api('queues/%2F/' + queue)
        result = {'runtime': runtime, 'requestsReconciled': 24, 'eventsReconciled': 72,
                  'brokerRestartRetainedEvents': 36, 'overflowFailedClosedExit': 70,
                  'overflowRetainedMessages': overflow_queue['messages_ready'], 'passed': True}
        (root / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    finally:
        # These containers are owned by this smoke. Keep their data and objects.
        for service in config['services']:
            (root / (service + '.log')).write_text(docker('logs', '--no-color', service).replace(password, '[REDACTED]'))
        docker('stop', '-t', '30')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--images', type=Path, help='Explicit matching mock/archive images.json from build.py')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(exist_ok=False)
    results = []
    settings = {'CAPTURE_IDENTITY_MODE': 'BENCHMARK_HEADERS'}
    if args.images is not None:
        images = json.loads(args.images.read_text())
        settings = {key.upper() + '_DIRECT_IMAGE': images[key]['tag'] for key in ('headless', 'official')}
        settings.update(ARCHIVE_IMAGE=images['archive']['tag'], CAPTURE_IDENTITY_MODE='BENCHMARK_HEADERS')
    for runtime in ('headless', 'official'):
        print('Testing ' + runtime, flush=True)
        results.append(trial(runtime, args.output / runtime, settings=settings))
        print(json.dumps(results[-1]), flush=True)
    (args.output / 'verification.json').write_text(json.dumps(results, indent=2) + '\n')
