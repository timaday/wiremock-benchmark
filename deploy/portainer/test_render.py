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
DIRECT = {
    'OFFICIAL_DIRECT_IMAGE': 'example.invalid/direct-official:test',
    'HEADLESS_DIRECT_IMAGE': 'example.invalid/direct-headless:test',
    'POCKETHIVE_RABBIT_URI': 'amqp://test:test@pockethive-rabbit:5672/bench',
    'POCKETHIVE_NETWORK': 'pockethive-overlay', 'RABBIT_QUEUE_TYPE': 'classic',
    'CAPTURE_CONFIRM_TIMEOUT_MS': '10000',
    'CAPTURE_IDENTITY_MODE': 'BENCHMARK_HEADERS',
}
DEDICATED = dict(DIRECT, ARCHIVE_IMAGE='example.invalid/archive@sha256:' + 'a' * 64,
                 RABBIT_NODE='broker-worker', ARCHIVE_NODE='archive-worker',
                 RABBIT_DATA_DIR='/srv/test/rabbit', ARCHIVE_DATA_DIR='/srv/test/archive',
                 RABBIT_PASSWORD='a' * 48, CAPTURE_QUEUE_MAX_BYTES='1073741824',
                 CAPTURE_QUEUE_MAX_MESSAGES='200000', RABBIT_DISK_FREE_LIMIT_BYTES='5368709120')

class SwarmConfigurationTest(unittest.TestCase):
    def test_stack_lists_are_indented_beneath_their_keys(self):
        for path in ROOT.glob('stack*.yml'):
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines[:-1]):
                if line.rstrip().endswith(':') and lines[index + 1].lstrip().startswith('- '):
                    with self.subTest(file=path.name, key=line.strip()):
                        self.assertGreater(len(lines[index + 1]) - len(lines[index + 1].lstrip()),
                                           len(line) - len(line.lstrip()))

    def render(self, file, **settings):
        excluded = {'RABBIT_PASSWORD', 'POCKETHIVE_RABBIT_URI', *DISTRIBUTED, *DIRECT, *DEDICATED}
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

    def test_direct_stacks_have_only_one_read_only_mock_and_external_broker(self):
        for runtime in ('official', 'headless'):
            with self.subTest(runtime=runtime):
                result = self.render(f'stack-direct-{runtime}.yml', **DIRECT)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = yaml.safe_load(result.stdout)
                self.assertEqual(set(config['services']), {runtime})
                self.assertNotIn('volumes', config)
                mock = config['services'][runtime]
                self.assertTrue(mock['read_only'])
                self.assertEqual(mock['image'], DIRECT[runtime.upper() + '_DIRECT_IMAGE'])
                self.assertEqual(mock['environment']['CAPTURE_MODE'], 'DIRECT_RABBIT')
                self.assertEqual(mock['environment']['CAPTURE_ENABLED'], 'true')
                self.assertNotIn('OUTBOX_PATH', mock['environment'])
                self.assertNotIn('/state', mock['environment']['JAVA_TOOL_OPTIONS'])
                self.assertEqual(mock['environment']['RABBIT_URI'], DIRECT['POCKETHIVE_RABBIT_URI'])
                self.assertEqual(mock['environment']['RABBIT_QUEUE'], 'test-capture.' + runtime)
                self.assertEqual(mock['environment']['WIREMOCK_ACCEPT_BACKLOG'], '4096')
                self.assertEqual(mock['volumes'][0]['type'], 'tmpfs')
                self.assertEqual(mock['volumes'][0]['target'], '/tmp')
                self.assertEqual(mock['volumes'][0]['tmpfs']['size'], 67108864)
                self.assertEqual(mock['deploy']['restart_policy'], {'condition': 'on-failure', 'delay': '5s'})
                self.assertTrue(config['networks']['pockethive']['external'])
                self.assertEqual(config['networks']['pockethive']['name'], DIRECT['POCKETHIVE_NETWORK'])

    def test_direct_stacks_require_new_image_and_explicit_broker_configuration(self):
        for runtime in ('official', 'headless'):
            for missing in ('POCKETHIVE_RABBIT_URI', 'POCKETHIVE_NETWORK', 'RABBIT_QUEUE_TYPE',
                            'CAPTURE_CONFIRM_TIMEOUT_MS', 'CAPTURE_IDENTITY_MODE', runtime.upper() + '_DIRECT_IMAGE'):
                with self.subTest(runtime=runtime, missing=missing):
                    settings = dict(DIRECT)
                    del settings[missing]
                    result = self.render(f'stack-direct-{runtime}.yml', **settings)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(missing, result.stderr)

    def test_direct_example_is_accepted_and_keeps_separate_ports(self):
        example = dict(line.split('=', 1) for line in (ROOT/'example-direct.env').read_text().splitlines()
                       if line and not line.startswith('#'))
        for runtime, port in [('official', 19280), ('headless', 19281)]:
            result = self.render(f'stack-direct-{runtime}.yml', **example)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(yaml.safe_load(result.stdout)['services'][runtime]['ports'][0]['published'], port)

    def test_dedicated_broker_stacks_isolate_capture_and_preserve_local_state(self):
        for runtime in ('official', 'headless'):
            result = self.render(f'stack-direct-{runtime}-rabbit.yml', **DEDICATED)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = yaml.safe_load(result.stdout)
            services = config['services']
            self.assertEqual(set(services), {runtime, 'rabbit', 'archive'})
            self.assertEqual(config['networks']['capture']['driver'], 'overlay')
            self.assertNotIn('external', config['networks']['capture'])
            mock, broker, archive = (services[key] for key in (runtime, 'rabbit', 'archive'))
            self.assertTrue(mock['read_only'])
            self.assertEqual(mock['environment']['CAPTURE_MODE'], 'DIRECT_RABBIT')
            self.assertEqual(mock['environment']['RABBIT_QUEUE_TYPE'], 'classic')
            self.assertEqual(mock['environment']['RABBIT_URI'], archive['environment']['RABBIT_URI'])
            self.assertIn('@rabbit:5672/', mock['environment']['RABBIT_URI'])
            self.assertEqual(mock['environment']['RABBIT_QUEUE'], archive['environment']['RABBIT_QUEUE'])
            self.assertEqual(broker['hostname'], 'rabbit')
            self.assertEqual(broker['environment']['RABBITMQ_NODENAME'], 'rabbit@rabbit')
            self.assertEqual({p['target'] for p in broker['ports']}, {15672})
            # Alarms must block publishing without creating a broker restart loop.
            self.assertNotIn('check_local_alarms', ' '.join(broker['healthcheck']['test']))
            for service, source, node in ((broker, '/srv/test/rabbit', 'broker-worker'),
                                          (archive, '/srv/test/archive', 'archive-worker')):
                self.assertEqual(service['volumes'][0]['source'], source)
                self.assertEqual(service['volumes'][0]['type'], 'bind')
                self.assertEqual(service['deploy']['placement']['constraints'], ['node.hostname == ' + node])
                self.assertEqual(service['deploy']['update_config']['order'], 'stop-first')
                self.assertIn('@sha256:', service['image'])

    def test_dedicated_stacks_require_storage_and_safety_limits(self):
        for missing in ('ARCHIVE_IMAGE', 'RABBIT_NODE', 'ARCHIVE_NODE', 'RABBIT_DATA_DIR', 'ARCHIVE_DATA_DIR',
                        'RABBIT_PASSWORD', 'CAPTURE_QUEUE_MAX_BYTES', 'CAPTURE_QUEUE_MAX_MESSAGES',
                        'RABBIT_DISK_FREE_LIMIT_BYTES'):
            settings = dict(DEDICATED)
            del settings[missing]
            result = self.render('stack-direct-headless-rabbit.yml', **settings)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(missing, result.stderr)

    def test_bootstrap_rejects_invalid_values_before_writing_configuration(self):
        for variable, value in [('RABBIT_PASSWORD', 'unsafe"password'), ('RABBIT_PASSWORD', 'abc'),
                                ('CAPTURE_QUEUE_MAX_MESSAGES', '0'), ('CAPTURE_QUEUE_MAX_BYTES', '-1'),
                                ('RABBIT_DISK_FREE_LIMIT_BYTES', '05')]:
            env = dict(os.environ, **DEDICATED)
            env[variable] = value
            result = subprocess.run(['/bin/sh', str(ROOT / 'direct/rabbit-bootstrap.sh')],
                                    env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(value, result.stderr)

    def test_dedicated_embedded_bootstrap_matches_canonical_source(self):
        source = (ROOT / 'direct/rabbit-bootstrap.sh').read_text()
        for runtime in ('official', 'headless'):
            config = yaml.safe_load((ROOT / f'stack-direct-{runtime}-rabbit.yml').read_text())
            embedded = config['services']['rabbit']['command'][0]
            self.assertEqual(embedded, source.replace('$', '$$'))
            self.assertIn('"overflow":"reject-publish"', source)
            self.assertNotIn('drop-head', source)

if __name__ == '__main__':
    unittest.main()
