"""Derive the standalone official capture-off stack from the canonical mock service.

Must not alter other stacks or add storage/broker dependencies.
Contract: OFFICIAL-NO-CAPTURE.md.
"""
import copy


def official_no_capture_stack(official):
    service = copy.deepcopy(official)
    backlog = '${WIREMOCK_ACCEPT_BACKLOG:-4096}'
    service['environment'] = {
        'CAPTURE_ENABLED': 'false',
        'FIXTURES': official['environment']['FIXTURES'],
        'JAVA_TOOL_OPTIONS': official['environment']['JAVA_TOOL_OPTIONS'],
        'WIREMOCK_ACCEPT_BACKLOG': backlog,
    }
    service['command'][service['command'].index('--jetty-accept-queue-size') + 1] = backlog
    service['ports'][0]['published'] = '${OFFICIAL_PORT:-19480}'
    del service['networks']
    return {'version': '3.8', 'services': {'official': service}}
