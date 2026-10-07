"""Render the dedicated broker/archive variation from canonical direct mock settings.

Own deployment composition only; do not redefine capture or archive behavior.
Contract: DIRECT-WITH-RABBIT.md.
"""
import copy
from pathlib import Path


def dedicated_stack(runtime, direct, broker_image, archive_image):
    mock = copy.deepcopy(direct)
    uri = 'amqp://benchmark:${RABBIT_PASSWORD:?set generated hexadecimal password}@rabbit:5672/%2f'
    mock['environment']['RABBIT_URI'] = uri
    mock['environment']['RABBIT_QUEUE_TYPE'] = 'classic'
    mock['networks'] = ['capture']
    logging = {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}}
    mock['logging'] = copy.deepcopy(logging)

    def deployment(node, cpu, memory):
        return {
            'replicas': 1,
            'placement': {'constraints': ['node.hostname == ${' + node + ':?set storage node hostname}']},
            'resources': {'limits': {'cpus': str(cpu), 'memory': memory}},
            'restart_policy': {'condition': 'on-failure', 'delay': '5s'},
            'update_config': {'parallelism': 1, 'order': 'stop-first'},
            'rollback_config': {'parallelism': 1, 'order': 'stop-first'},
        }

    bootstrap = (Path(__file__).parent / 'direct/rabbit-bootstrap.sh').read_text()
    rabbit = {
        'image': broker_image,
        'hostname': 'rabbit',
        'environment': {
            'RABBITMQ_NODENAME': 'rabbit@rabbit',
            'RABBIT_PASSWORD': '${RABBIT_PASSWORD:?set generated hexadecimal password}',
            'CAPTURE_QUEUE_MAX_BYTES': '${CAPTURE_QUEUE_MAX_BYTES:?required}',
            'CAPTURE_QUEUE_MAX_MESSAGES': '${CAPTURE_QUEUE_MAX_MESSAGES:?required}',
            'RABBIT_DISK_FREE_LIMIT_BYTES': '${RABBIT_DISK_FREE_LIMIT_BYTES:?required}',
        },
        'entrypoint': ['/bin/sh', '-ec'],
        'command': [bootstrap.replace('$', '$$')],
        'volumes': [{'type': 'bind', 'source': '${RABBIT_DATA_DIR:?set existing local broker directory}',
                     'target': '/var/lib/rabbitmq'}],
        'ports': [{'target': 15672, 'published': '${RABBIT_UI_PORT:-15675}',
                   'protocol': 'tcp', 'mode': 'ingress'}],
        'healthcheck': {
            'test': ['CMD-SHELL', 'rabbitmq-diagnostics -q check_running && '
                     'rabbitmq-diagnostics -q check_port_connectivity'],
            'interval': '30s', 'timeout': '20s', 'retries': 3, 'start_period': '60s'},
        'deploy': deployment('RABBIT_NODE', 2, '2G'),
        'stop_grace_period': '120s', 'networks': ['capture'], 'logging': copy.deepcopy(logging),
    }
    archive = {
        'image': archive_image,
        'environment': {'RABBIT_URI': uri, 'RABBIT_QUEUE': mock['environment']['RABBIT_QUEUE'],
                        'ARCHIVE_PATH': '/archive/events.db',
                        'JAVA_TOOL_OPTIONS': '-XX:+ExitOnOutOfMemoryError'},
        'volumes': [{'type': 'bind', 'source': '${ARCHIVE_DATA_DIR:?set existing local archive directory}',
                     'target': '/archive'}],
        'healthcheck': {'test': ['CMD-SHELL', 'test -s /archive/events.db && test -w /archive/events.db'],
                        'interval': '30s', 'timeout': '5s', 'retries': 3, 'start_period': '60s'},
        'deploy': deployment('ARCHIVE_NODE', 2, '1G'),
        'stop_grace_period': '60s', 'networks': ['capture'], 'logging': copy.deepcopy(logging),
    }
    return {'version': '3.8', 'services': {runtime: mock, 'rabbit': rabbit, 'archive': archive},
            'networks': {'capture': {'driver': 'overlay'}}}
