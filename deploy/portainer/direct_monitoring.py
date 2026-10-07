"""Compose optional direct-capture monitoring and derive its dashboard.

Must not change capture services or infer reconciliation from telemetry.
Contract: DIRECT-WITH-RABBIT.md and docs/CONTRACT.md.
"""
import copy
import json

from yaml_format import stack_yaml


def direct_dashboard(comparison, runtime):
    dashboard = copy.deepcopy(comparison)
    dashboard.update(uid='wiremock-direct', title=f'WireMock {runtime} capture', version=1)
    variable = dashboard['templating']['list'][0]
    variable.update(query=runtime, multi=False, includeAll=False,
                    current={'text': runtime, 'value': runtime})
    variable.pop('allValue')
    panels = dashboard['panels']
    panels[0]['title'] = 'Direct capture: HTTP → RabbitMQ → archive'
    panels[0]['options']['content'] = (
        'HTTP charts count capture-enabled mappings in STUB_JSON mode, or admitted `/bench/` '
        'requests in BENCHMARK_HEADERS mode. Duration includes the configured delay. '
        'Capture waiting events are awaiting broker confirmation, not a disk outbox. '
        'Expect three capture events per completed exchange after drain. Queue consumers '
        'and acknowledgements show archive-consumer activity; they do not prove reconciliation. '
        'Disk headroom is for RabbitMQ only. Archive disk, host swapping and container RSS '
        'are not measured. Missing data is not a healthy zero. No notification receiver is configured.')
    for panel in panels:
        if panel['title'] == 'Capture outbox pending events':
            panel['title'] = 'Capture events awaiting broker confirmation'
        if panel['title'] == 'Telemetry available (1 = up)':
            panel['targets'][0].update(expr='up', legendFormat='{{job}}')

    def append(title, expressions, unit, legends):
        # Derive formatting from the canonical comparison panel, not a second style owner.
        panel = copy.deepcopy(panels[1])
        index = len(panels)
        panel.update(id=index + 1, title=title,
                     gridPos={'x': ((index - 1) % 2) * 12,
                              'y': 4 + ((index - 1) // 2) * 8, 'w': 12, 'h': 8})
        panel['fieldConfig']['defaults']['unit'] = unit
        panel['targets'] = [dict(panel['targets'][0], refId=chr(65 + i), expr=expr,
                                 legendFormat=legends[i]) for i, expr in enumerate(expressions)]
        panels.append(panel)

    append('Archive consumers (expected 1 per queue)', ['rabbitmq_detailed_queue_consumers'],
           'short', ['{{queue}}'])
    append('Archive consumer acknowledgements / second',
           ['rate(rabbitmq_channel_messages_acked_total[$__rate_interval])'], 'ops', ['acknowledged'])
    append('RabbitMQ free disk / disk alarm limit',
           ['rabbitmq_disk_space_available_bytes', 'rabbitmq_disk_space_available_limit_bytes'],
           'bytes', ['free disk', 'alarm limit'])
    append('RabbitMQ memory used / memory alarm limit',
           ['rabbitmq_process_resident_memory_bytes', 'rabbitmq_resident_memory_limit_bytes'],
           'bytes', ['resident memory', 'alarm limit'])
    append('Capture publish confirmation batch mean duration',
           ['rate(wiremock_capture_publish_confirm_seconds_total[$__rate_interval]) / '
            'rate(wiremock_capture_publish_confirm_count[$__rate_interval])'], 's', ['{{runtime}}'])
    append('Rejected requests / second',
           ['rate(wiremock_capture_rejected_requests_total[$__rate_interval])'], 'reqps', ['{{runtime}}'])
    return dashboard


def embedded_command(files, executable):
    """Write fixed generated configuration, preserving dollar signs through Compose and sh."""
    script = 'set -eu\n'
    for index, (path, content) in enumerate(files.items()):
        marker = f'WIREMOCK_CONFIG_{index}'
        if marker in content.splitlines():
            raise ValueError('Configuration contains heredoc delimiter')
        script += f"mkdir -p {path.rsplit('/', 1)[0]}\ncat > {path} <<'{marker}'\n{content}\n{marker}\n"
    return [(script + 'exec ' + executable + '\n').replace('$', '$$')]


def monitored_stack(runtime, dedicated, images, comparison, datasource):
    stack = copy.deepcopy(dedicated)
    logging = copy.deepcopy(stack['services']['rabbit']['logging'])
    deployment = copy.deepcopy(stack['services']['archive']['deploy'])
    deployment['placement']['constraints'] = ['node.hostname == ${MONITORING_NODE:?set monitoring node hostname}']
    deployment['resources']['limits'] = {'cpus': '1', 'memory': '1G'}
    config = {'global': {'scrape_interval': '5s', 'scrape_timeout': '4s'}, 'scrape_configs': [
        {'job_name': 'wiremock', 'metrics_path': '/prometheus', 'static_configs': [
            {'targets': [runtime + ':8081'], 'labels': {'runtime': runtime}}]},
        {'job_name': 'rabbit', 'static_configs': [{'targets': ['rabbit:15692']}]},
        {'job_name': 'rabbit-queues', 'metrics_path': '/metrics/detailed',
         'params': {'family': ['queue_coarse_metrics', 'queue_consumer_count']},
         'static_configs': [{'targets': ['rabbit:15692']}]},
    ]}
    prometheus = {
        'image': images['prometheus']['reference'], 'entrypoint': ['/bin/sh', '-ec'],
        'command': embedded_command({'/tmp/wiremock/prometheus.yml': stack_yaml(config)},
            '/bin/prometheus --config.file=/tmp/wiremock/prometheus.yml --storage.tsdb.path=/prometheus '
            '--storage.tsdb.retention.time=7d --storage.tsdb.retention.size=2GB'),
        'volumes': [{'type': 'bind', 'source': '${PROMETHEUS_DATA_DIR:?set existing local metrics directory}',
                     'target': '/prometheus'}],
        'healthcheck': {'test': ['CMD', 'wget', '-q', '-O', '/dev/null', 'http://localhost:9090/-/ready'],
                        'interval': '15s', 'timeout': '5s', 'retries': 4, 'start_period': '60s'},
        'deploy': copy.deepcopy(deployment), 'stop_grace_period': '60s',
        'networks': ['capture'], 'logging': logging,
    }
    provision = {'apiVersion': 1, 'providers': [
        {'name': 'Direct capture', 'folder': 'WireMock', 'type': 'file', 'disableDeletion': True,
         'editable': False, 'options': {'path': '/tmp/wiremock/dashboards'}}]}
    grafana = {
        'image': images['grafana']['reference'], 'entrypoint': ['/bin/sh', '-ec'],
        'command': embedded_command({
            '/tmp/wiremock/provisioning/datasources/prometheus.yml': stack_yaml(datasource),
            '/tmp/wiremock/provisioning/dashboards/direct.yml': stack_yaml(provision),
            '/tmp/wiremock/dashboards/direct.json': json.dumps(direct_dashboard(comparison, runtime)),
        }, '/run.sh'),
        'environment': {'GF_PATHS_PROVISIONING': '/tmp/wiremock/provisioning',
                        'GF_SECURITY_ADMIN_USER': '${GRAFANA_USER:?set Grafana username}',
                        'GF_SECURITY_ADMIN_PASSWORD': '${GRAFANA_PASSWORD:?set Grafana password}',
                        'GF_USERS_ALLOW_SIGN_UP': 'false', 'GOMEMLIMIT': '512MiB'},
        'volumes': [{'type': 'bind', 'source': '${GRAFANA_DATA_DIR:?set existing local dashboard directory}',
                     'target': '/var/lib/grafana'}],
        'ports': [{'target': 3000, 'published': '${GRAFANA_PORT:-13300}',
                   'protocol': 'tcp', 'mode': 'ingress'}],
        'healthcheck': {'test': ['CMD', 'wget', '-q', '-O', '/dev/null', 'http://localhost:3000/api/health'],
                        'interval': '15s', 'timeout': '5s', 'retries': 4, 'start_period': '60s'},
        'deploy': copy.deepcopy(deployment), 'stop_grace_period': '30s',
        'networks': ['capture'], 'logging': copy.deepcopy(logging),
    }
    stack['services'].update(prometheus=prometheus, grafana=grafana)
    return stack
