"""Regression checks for Swarm interpolation and the explicit external-broker mode."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parent
PLACEMENTS = {
    'OFFICIAL_NODE': 'mock-worker', 'HEADLESS_NODE': 'mock-worker',
    'RABBIT_NODE': 'broker-worker', 'ARCHIVE_NODE': 'archive-worker',
    'MONITORING_NODE': 'monitoring-node',
}
DISTRIBUTED = dict(PLACEMENTS, OFFICIAL_REPLICAS='0', HEADLESS_REPLICAS='1')

class SwarmConfigurationTest(unittest.TestCase):
    def render(self, file, **settings):
        excluded = {'RABBIT_PASSWORD', 'POCKETHIVE_RABBIT_URI', *DISTRIBUTED}
        env = {k:v for k,v in os.environ.items() if k not in excluded}
        env.update(LAB_NODE='test-node', CAPTURE_PREFIX='test-capture', GRAFANA_PASSWORD='test-only-grafana', WIREMOCK_ACCEPT_BACKLOG='4096')
        env.update(settings)
        return subprocess.run(['docker','stack','config','-c',str(ROOT/file)],env=env,text=True,capture_output=True)

    def test_standalone_password_interpolates_exactly_and_is_required(self):
        result = self.render('stack.yml', RABBIT_PASSWORD='test-only-rabbit')
        self.assertEqual(result.returncode,0,result.stderr)
        services=yaml.safe_load(result.stdout)['services']
        self.assertEqual(services['rabbit']['environment']['RABBITMQ_DEFAULT_PASS'],'test-only-rabbit')
        for name in ['official','headless','official-archive','headless-archive']:
            self.assertEqual(services[name]['environment']['RABBIT_URI'],'amqp://benchmark:test-only-rabbit@rabbit:5672/%2f')
        self.assertNotEqual(self.render('stack.yml').returncode,0)

    def test_backlog_reaches_both_runtimes_in_every_stack(self):
        for filename in ['stack.yml', 'stack-pockethive.yml', 'stack-ghcr.yml',
                         'stack-ghcr-pockethive.yml', 'stack-ghcr-distributed.yml']:
            with self.subTest(filename=filename):
                settings = dict(RABBIT_PASSWORD='test-only-rabbit',
                                POCKETHIVE_RABBIT_URI='amqp://test:test@broker:5672/bench',
                                **DISTRIBUTED)
                result = self.render(filename, WIREMOCK_ACCEPT_BACKLOG='2048', **settings)
                self.assertEqual(result.returncode, 0, result.stderr)
                services = yaml.safe_load(result.stdout)['services']
                command = services['official']['command']
                self.assertEqual(command[command.index('--jetty-accept-queue-size') + 1], '2048')
                for runtime in ['official', 'headless']:
                    self.assertEqual(services[runtime]['environment']['WIREMOCK_ACCEPT_BACKLOG'], '2048')
                self.assertNotEqual(self.render(filename, WIREMOCK_ACCEPT_BACKLOG='', **settings).returncode, 0)

    def test_pockethive_mode_uses_only_explicit_existing_broker(self):
        uri='amqp://test:test@pockethive.example.invalid:5672/bench'
        result=self.render('stack-pockethive.yml',POCKETHIVE_RABBIT_URI=uri)
        self.assertEqual(result.returncode,0,result.stderr)
        config=yaml.safe_load(result.stdout)
        self.assertNotIn('rabbit',config['services'])
        self.assertNotIn('rabbit',config['volumes'])
        for name in ['official','headless','official-archive','headless-archive']:
            self.assertEqual(config['services'][name]['environment']['RABBIT_URI'],uri)
        self.assertNotEqual(self.render('stack-pockethive.yml').returncode,0)

    def test_distributed_placement_and_runtime_selection_preserve_capture(self):
        baseline = yaml.safe_load(self.render('stack-ghcr.yml', RABBIT_PASSWORD='test-only-rabbit').stdout)
        for official, headless in [('0', '1'), ('1', '0')]:
            with self.subTest(official=official, headless=headless):
                settings = dict(DISTRIBUTED, OFFICIAL_REPLICAS=official, HEADLESS_REPLICAS=headless,
                                RABBIT_PASSWORD='test-only-rabbit')
                result = self.render('stack-ghcr-distributed.yml', **settings)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = yaml.safe_load(result.stdout)
                expected_nodes = {
                    'official': 'mock-worker', 'headless': 'mock-worker', 'rabbit': 'broker-worker',
                    'official-archive': 'archive-worker', 'headless-archive': 'archive-worker',
                    'prometheus': 'monitoring-node', 'grafana': 'monitoring-node',
                }
                self.assertEqual(config['volumes'], baseline['volumes'])
                self.assertEqual(config['networks']['default']['driver'], 'overlay')
                for name, node in expected_nodes.items():
                    service = config['services'][name]
                    deployment = service['deploy']
                    self.assertEqual(deployment['placement']['constraints'], ['node.hostname == ' + node])
                    self.assertEqual(deployment['update_config']['order'], 'stop-first')
                    self.assertEqual(deployment['rollback_config']['order'], 'stop-first')
                    replicas = int(settings[name.upper() + '_REPLICAS']) if name in ['official', 'headless'] else 1
                    self.assertEqual(deployment['replicas'], replicas)
                    # Apart from placement/update order/selection, preserve the original configuration.
                    service['deploy'] = baseline['services'][name]['deploy']
                    self.assertEqual(service, baseline['services'][name])

    def test_distributed_requires_every_node_and_runtime_selection(self):
        for missing in DISTRIBUTED:
            with self.subTest(missing=missing):
                settings = dict(DISTRIBUTED, RABBIT_PASSWORD='test-only-rabbit')
                del settings[missing]
                result = self.render('stack-ghcr-distributed.yml', **settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)

    def test_distributed_example_ports_do_not_collide_with_original_defaults(self):
        example = dict(line.split('=', 1) for line in (ROOT/'example-distributed.env').read_text().splitlines()
                       if line and not line.startswith('#'))
        result = self.render('stack-ghcr-distributed.yml', **example)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = yaml.safe_load(result.stdout)['services']
        actual = {port['published'] for service in services.values() for port in service.get('ports', [])}
        self.assertEqual(actual, {19180, 19181, 13100, 29190, 5674, 15674})

if __name__ == '__main__':
    unittest.main()
