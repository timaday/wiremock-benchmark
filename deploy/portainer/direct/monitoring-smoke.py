#!/usr/bin/env python3
"""Verify published monitoring stacks locally with real captures and queue drain.

Use fresh directories, bridge networking and loopback ports; retain stopped
containers and evidence. Does not deploy to Swarm or qualify throughput.
Contract: ../DIRECT-WITH-RABBIT.md.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
import zlib

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from yaml_format import stack_yaml

spec = importlib.util.spec_from_file_location('dedicated_smoke', Path(__file__).with_name('dedicated-smoke.py'))
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def trial(runtime, output):
    output.mkdir()
    settings = {}
    for name in ('example-direct-rabbit.env', 'example-direct-monitoring.env'):
        settings.update(dict(line.split('=', 1) for line in (ROOT / name).read_text().splitlines()
                             if line and not line.startswith('#')))
    for name, variable in [('rabbit', 'RABBIT_DATA_DIR'), ('archive', 'ARCHIVE_DATA_DIR'),
                           ('prometheus', 'PROMETHEUS_DATA_DIR'), ('grafana', 'GRAFANA_DATA_DIR')]:
        path = output / name
        path.mkdir()
        # Only this disposable test's empty directories; deployed paths use documented ownership.
        path.chmod(0o777)
        settings[variable] = str(path)
    password = secrets.token_hex(24)
    settings.update(RABBIT_PASSWORD=password, GRAFANA_PASSWORD=password,
                    CAPTURE_PREFIX='monitoring-' + secrets.token_hex(4))
    env = dict(os.environ, **settings)
    config = yaml.safe_load((ROOT / f'stack-direct-{runtime}-rabbit-monitored.yml').read_text())
    config['networks']['capture'] = {'driver': 'bridge'}
    for service in config['services'].values():
        limits = service.pop('deploy')['resources']['limits']
        service.update(cpus=limits['cpus'], mem_limit=limits['memory'])
        for port in service.get('ports', []):
            port.update(published=0, host_ip='127.0.0.1')
            port.pop('mode')
    compose = output / 'compose.yml'
    compose.write_text(stack_yaml(config))
    project = 'direct-monitor-' + runtime + '-' + secrets.token_hex(4)
    command = ['docker', 'compose', '-p', project, '-f', str(compose)]

    def docker(*args):
        result = subprocess.run([*command, *args], env=env, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(password, '[REDACTED]'))
        return result.stdout.strip()

    def endpoint(service, port):
        return 'http://' + docker('port', service, str(port))

    def request(url, body=None, user=None):
        headers = {'Content-Type': 'application/json'}
        if user:
            headers['Authorization'] = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
            return json.loads(data) if data else response.status

    try:
        print(runtime + ': starting dedicated RabbitMQ', flush=True)
        docker('up', '-d', '--pull', 'never', 'rabbit')
        rabbit_url = endpoint('rabbit', 15672)
        helpers.wait_for(lambda: request(rabbit_url + '/api/overview', user='benchmark'))
        docker('up', '-d', '--pull', 'never', runtime, 'archive', 'prometheus', 'grafana')
        mock_url = endpoint(runtime, 8080)
        grafana_url = endpoint('grafana', 3000)
        helpers.wait_for(lambda: request(mock_url + '/__admin/health'))
        helpers.wait_for(lambda: request(grafana_url + '/api/health')['database'] == 'ok')
        dashboard = request(grafana_url + '/api/dashboards/uid/wiremock-direct', user='admin')['dashboard']
        assert '$__rate_interval' in json.dumps(dashboard) and '$$__rate_interval' not in json.dumps(dashboard)
        assert dashboard['templating']['list'][0]['query'] == runtime
        (output / 'dashboard.json').write_text(json.dumps(dashboard, indent=2) + '\n')

        def query(expression):
            response = request(grafana_url + '/api/datasources/proxy/uid/wiremock-prometheus/api/v1/query?'
                               + urllib.parse.urlencode({'query': expression}), user='admin')
            assert response['status'] == 'success'
            return response['data']['result']

        def equals(expression, expected):
            rows = query(expression)
            return len(rows) == 1 and float(rows[0]['value'][1]) == expected

        helpers.wait_for(lambda: equals('sum(up)', 3))
        run_id = project
        request(mock_url + '/__admin/mappings', {
            'request': {'method': 'POST', 'urlPath': '/monitoring-smoke'},
            'response': {'status': 200, 'fixedDelayMilliseconds': 6000,
                         'transformerParameters': {'capture': {
                             'runId': run_id, 'correlationJsonPath': '$.correlationId',
                             'missingCorrelation': 'RECORD_UNCORRELATED'}}}})

        def send(index):
            assert request(mock_url + '/monitoring-smoke', {'correlationId': 'monitor-' + str(index)}) == 200

        send(0)
        helpers.wait_for(lambda: equals('rabbitmq_detailed_queue_consumers', 1))
        docker('stop', 'archive')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(send, (1, 2)))
        helpers.wait_for(lambda: equals('rabbitmq_detailed_queue_messages_ready', 6))
        helpers.wait_for(lambda: equals('rabbitmq_detailed_queue_consumers', 0))
        print(runtime + ': dashboard sees queued captures with archive paused', flush=True)
        docker('start', 'archive')
        helpers.wait_for(lambda: equals('rabbitmq_detailed_queue_messages_ready', 0))
        helpers.wait_for(lambda: equals('rabbitmq_detailed_queue_consumers', 1))
        helpers.wait_for(lambda: equals('wiremock_http_completed_total', 3))
        helpers.wait_for(lambda: equals('wiremock_capture_confirmed_total', 9))

        expressions = [target['expr'].replace('$__rate_interval', '1m').replace('$runtime', runtime)
                       for panel in dashboard['panels'] for target in panel.get('targets', [])]
        samples = {}
        for expression in expressions:
            rows = query(expression)
            assert rows, 'Dashboard query has no data: ' + expression
            samples[expression] = rows
        (output / 'metric-samples.json').write_text(json.dumps(samples, indent=2) + '\n')
        with sqlite3.connect(f'file:{output}/archive/events.db?mode=ro', uri=True) as db:
            records = [json.loads(zlib.decompress(row[0])) for row in db.execute(
                'SELECT payload_zlib FROM events WHERE run_id=?', (run_id,))]
        assert len(records) == 9
        for index in range(3):
            events = [event for event in records if event['correlationId'] == 'monitor-' + str(index)]
            assert {event['phase'] for event in events} == {'REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'}
        assert equals('wiremock_capture_errors_total', 0)
        helpers.wait_for(lambda: all(item['Health'] == 'healthy' for item in
                                    map(json.loads, docker('ps', '--format', 'json').splitlines())))
        report = {'runtime': runtime, 'requests': 3, 'captures': 9, 'delayMs': 6000,
                  'scrapeTargetsUp': 3, 'dashboardQueriesWithData': len(samples),
                  'pausedArchiveQueueReady': 6, 'pausedArchiveConsumers': 0,
                  'finalQueueReady': 0, 'finalConsumers': 1, 'captureErrors': 0,
                  'allServiceHealthchecksPassed': True, 'project': project}
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        print(runtime + ': monitoring and archive verification passed', flush=True)
        return report
    finally:
        (output / 'logs.txt').write_text(docker('logs', '--no-color').replace(password, '[REDACTED]'))
        docker('stop', '--timeout', '30')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(exist_ok=False)
    reports = [trial(runtime, root / runtime) for runtime in ('headless', 'official')]
    (root / 'verification.json').write_text(json.dumps(reports, indent=2) + '\n')
