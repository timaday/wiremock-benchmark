#!/usr/bin/env python3
"""Exercise bad requests, complete captures and supervised broker-outage recovery.

Responsibility: test the two built images against an isolated disposable RabbitMQ.
Must not: use PocketHive credentials, delete evidence, or claim Swarm/hour qualification.
Contract: DIRECT-RABBIT.md and docs/CONTRACT.md. Created containers are stopped and retained.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'deploy/portainer'))
from smoke import check


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def inspect(name):
    return json.loads(docker('inspect', name))[0]


def address(name, port):
    return docker('port', name, str(port))


def wait_until(description, predicate, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.5)
    raise AssertionError('Timed out: ' + description)


def healthy(name):
    try:
        with urllib.request.urlopen('http://' + address(name, 8080) + '/__admin/health', timeout=2) as r:
            return r.status == 200
    except (OSError, http.client.HTTPException, subprocess.CalledProcessError):
        return False


def request(name, headers, body=b'{}', path='/bench/static-1024-0'):
    conn = http.client.HTTPConnection(address(name, 8080), timeout=15)
    try:
        conn.putrequest('POST', path)
        conn.putheader('Content-Length', str(len(body)))
        conn.putheader('Content-Type', 'application/json')
        for key, value in headers:
            conn.putheader(key, value)
        conn.endheaders(body)
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


def metrics(name):
    with urllib.request.urlopen('http://' + address(name, 8081) + '/metrics', timeout=5) as r:
        return json.load(r)


def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    prefix = 'wm-direct-proof-' + uuid.uuid4().hex[:10]
    broker = prefix + '-rabbit'
    queue_prefix = prefix + '.captures'
    created = []
    report = {'oneHourQualification': False, 'remoteSwarmDeployment': False,
              'supervisor': 'local Docker on-failure; Swarm restart policy separately parser-tested',
              'brokerStorage': 'tmpfs: protocol/recovery proof, not power-loss durability proof'}
    try:
        docker('network', 'create', prefix)
        lock = json.loads((ROOT / 'deploy/portainer/image-lock.json').read_text())
        docker('run', '-d', '--name', broker, '--network', prefix,
               '--tmpfs', '/var/lib/rabbitmq:rw,size=256m', '-p', '127.0.0.1::5672',
               '--health-cmd', 'rabbitmq-diagnostics -q check_port_connectivity',
               '--health-interval', '5s', '--health-timeout', '5s', '--health-retries', '12',
               '-e', 'RABBITMQ_DEFAULT_USER=direct-test', '-e', 'RABBITMQ_DEFAULT_PASS=direct-test-only',
               lock['images']['rabbit']['reference'])
        created.append(broker)
        wait_until('broker ready', lambda: inspect(broker)['State'].get('Health', {}).get('Status') == 'healthy')
        mocks = {}
        image_ids = {}
        for runtime, image in [('official', args.official_image), ('headless', args.headless_image)]:
            spec = yaml.safe_load((ROOT / f'deploy/portainer/stack-direct-{runtime}.yml').read_text())['services'][runtime]
            env = spec['environment'] | {
                'RABBIT_URI': f'amqp://direct-test:direct-test-only@{broker}:5672/%2f',
                'RABBIT_QUEUE': queue_prefix + '.' + runtime, 'RABBIT_QUEUE_TYPE': 'classic',
                'CAPTURE_CONFIRM_TIMEOUT_MS': '3000', 'WIREMOCK_ACCEPT_BACKLOG': '4096'}
            name = prefix + '-' + runtime
            command = ['run', '-d', '--name', name, '--network', prefix, '--restart', 'on-failure',
                       '--read-only', '--tmpfs', '/tmp:rw,size=64m', '--cpus', '4', '--memory', '4g',
                       '-p', '127.0.0.1::8080', '-p', '127.0.0.1::8081']
            for key, value in env.items():
                command += ['-e', f'{key}={value}']
            command += [image] + ['4096' if '${WIREMOCK_ACCEPT_BACKLOG' in v else v for v in spec.get('command', [])]
            docker(*command)
            created.append(name)
            mocks[runtime] = name
            wait_until(runtime + ' ready', lambda: healthy(name))
            state = inspect(name)
            image_ids[runtime] = state['Image']
            assert state['HostConfig']['ReadonlyRootfs']
            assert all(m['Type'] == 'tmpfs' for m in state['Mounts'])
        report['images'] = image_ids
        rejected = {}
        for runtime, name in mocks.items():
            pid = inspect(name)['State']['Pid']
            bad = [([], b'{}', 400), ([('X-Bench-Run', 'run')], b'{}', 400),
                   ([('X-Bench-Id', 'id')], b'{}', 400),
                   ([('X-Bench-Run', 'run'), ('X-Bench-Id', '')], b'{}', 400),
                   ([('X-Bench-Run', 'run'), ('X-Bench-Id', ' ')], b'{}', 400),
                   ([('X-Bench-Run', 'run'), ('X-Bench-Id', 'x' * 257)], b'{}', 400),
                   ([('X-Bench-Run', 'run'), ('X-Bench-Id', 'a'), ('X-Bench-Id', 'b')], b'{}', 400),
                   ([('X-Bench-Run', 'run'), ('X-Bench-Id', 'id')], b'x' * 65537, 413)]
            for headers, body, status in bad:
                assert request(name, headers, body) == status
                assert healthy(name) and inspect(name)['State']['Pid'] == pid
            assert request(name, [], path='/not-a-benchmark-route') == 404
            state = metrics(name)
            assert state['rejectedRequests'] == len(bad) and state['errors'] == 0
            assert state['confirmed'] == 0 and state['pending'] == 0
            assert inspect(name)['RestartCount'] == 0
            rejected[runtime] = {'badRequests': len(bad), 'sameProcess': True, 'restartCount': 0}
        report['clientRejections'] = rejected

        subprocess.run(['javac', '-cp', str(ROOT / 'target/capture.jar'), '-d', str(ROOT / 'target/direct-smoke'),
                        str(ROOT / 'tests/perf/DirectCaptureReadback.java')], check=True)

        def verify_captures(stage):
            runs = [check('http://' + address(name, 8080), runtime) for runtime, name in mocks.items()]
            clients = output / f'{stage}-clients.json'
            clients.write_text(json.dumps(runs, indent=2) + '\n')
            env = os.environ | {'CAPTURE_TEST_RABBIT_URI':
                                f'amqp://direct-test:direct-test-only@{address(broker, 5672)}/%2f'}
            subprocess.run(['java', '-cp', str(ROOT / 'target/capture.jar') + ':' + str(ROOT / 'target/direct-smoke'),
                            'bench.DirectCaptureReadback', str(clients), queue_prefix,
                            str(output / f'{stage}-captures.json')], env=env, check=True)
            for name in mocks.values():
                state = metrics(name)
                assert state['mode'] == 'DIRECT_RABBIT' and state['pending'] == 0 and state['confirmed'] == 36
                assert state['errors'] == 0 and state['brokerConnected']
            report[stage] = {'requests': 24, 'exactCaptures': 72, 'minimumDelaySeconds': 6,
                             'metrics': {runtime: metrics(name) for runtime, name in mocks.items()}}

        verify_captures('before-outage')
        docker('stop', '--timeout', '5', broker)
        for name in mocks.values():
            try:
                status = request(name, [('X-Bench-Run', 'outage'), ('X-Bench-Id', 'failed-request')])
                assert status >= 400, 'Capture failure was reported as HTTP success'
            except (OSError, http.client.HTTPException):
                pass
            wait_until('mock restarted after capture fault', lambda: inspect(name)['RestartCount'] > 0)
            log = subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT, text=True)
            assert 'FATAL: durable capture unavailable' in log
        docker('start', broker)
        wait_until('broker restored', lambda: inspect(broker)['State'].get('Health', {}).get('Status') == 'healthy')
        for name in mocks.values():
            wait_until('mock recovered automatically', lambda: healthy(name))
        report['recoveryRestartCounts'] = {runtime: inspect(name)['RestartCount'] for runtime, name in mocks.items()}
        verify_captures('after-recovery')
        report['passed'] = True
        print('PASS: bad requests survived; 48 valid HTTP responses / 144 captures; automatic recovery')
    finally:
        report['retainedContainers'] = created
        report['retainedNetwork'] = prefix
        for name in reversed(created):
            with (output / f'{name}.log').open('w') as log:
                subprocess.run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT, check=False)
            subprocess.run(['docker', 'stop', '--timeout', '5', name], stdout=subprocess.DEVNULL, check=False)
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official-image', required=True)
    parser.add_argument('--headless-image', required=True)
    parser.add_argument('--output', required=True, type=Path)
    main(parser.parse_args())
