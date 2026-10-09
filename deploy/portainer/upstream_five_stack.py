"""Derive five unextended upstream servers from the canonical official tuning.

Must not include custom images, extension flags, baked mappings or persistent data.
Contract: OFFICIAL-FIVE.md.
"""
import copy

from no_capture_stack import official_no_capture_stack
from upstream_five_proxy import nginx_service


UPSTREAM_IMAGE = ('wiremock/wiremock:3.13.2@sha256:'
                  '0d4ecb3e4dc8213fd7a4d37d6a78f6e6b553a6d2e15bd51b0999781282ac61b3')


def upstream_five_stack(official):
    base = official_no_capture_stack(official)['services']['official']
    base['image'] = UPSTREAM_IMAGE
    base['environment'] = {'JAVA_TOOL_OPTIONS': base['environment']['JAVA_TOOL_OPTIONS']}
    extension_index = base['command'].index('--extensions')
    del base['command'][extension_index:extension_index + 2]
    services = {}
    for number in range(1, 6):
        service = copy.deepcopy(base)
        service['ports'][0]['published'] = 19000 + number
        service['deploy']['placement']['constraints'] = [
            'node.hostname == ${WIREMOCK_' + str(number) + '_NODE:?set Swarm node hostname}'
        ]
        services[f'wiremock-{number}'] = service
    services['nginx'] = nginx_service()
    return {'version': '3.8', 'services': services}
