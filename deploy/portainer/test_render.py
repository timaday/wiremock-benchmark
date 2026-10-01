"""Regression checks for Swarm interpolation and the explicit external-broker mode."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parent

class SwarmConfigurationTest(unittest.TestCase):
    def render(self, file, **settings):
        env = {k:v for k,v in os.environ.items() if k not in ['RABBIT_PASSWORD','POCKETHIVE_RABBIT_URI']}
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
                         'stack-ghcr-pockethive.yml']:
            with self.subTest(filename=filename):
                settings = dict(RABBIT_PASSWORD='test-only-rabbit',
                                POCKETHIVE_RABBIT_URI='amqp://test:test@broker:5672/bench')
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

if __name__ == '__main__':
    unittest.main()
