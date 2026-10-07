"""Check deployable monitoring isolation, required storage and embedded provisioning."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parent


class DirectMonitoringTest(unittest.TestCase):
    def settings(self):
        settings = {}
        for name in ('example-direct-rabbit.env', 'example-direct-monitoring.env'):
            settings.update(dict(line.split('=', 1) for line in (ROOT / name).read_text().splitlines()
                                 if line and not line.startswith('#')))
        return settings

    def render(self, runtime, settings):
        env = {key: value for key, value in os.environ.items() if key not in self.settings()}
        env.update(settings)
        return subprocess.run(['docker', 'stack', 'config', '-c',
                               str(ROOT / f'stack-direct-{runtime}-rabbit-monitored.yml')],
                              env=env, text=True, capture_output=True)

    def test_capture_services_are_unchanged_and_monitoring_is_isolated(self):
        images = json.loads((ROOT / 'image-lock.json').read_text())['images']
        for runtime in ('headless', 'official'):
            raw = yaml.safe_load((ROOT / f'stack-direct-{runtime}-rabbit-monitored.yml').read_text())
            base = yaml.safe_load((ROOT / f'stack-direct-{runtime}-rabbit.yml').read_text())
            self.assertEqual({k: raw['services'][k] for k in base['services']}, base['services'])
            self.assertEqual(raw['networks'], base['networks'])
            result = self.render(runtime, self.settings())
            self.assertEqual(result.returncode, 0, result.stderr)
            services = yaml.safe_load(result.stdout)['services']
            self.assertEqual(set(services), {runtime, 'rabbit', 'archive', 'prometheus', 'grafana'})
            self.assertNotIn('ports', services['prometheus'])
            self.assertEqual(services['grafana']['ports'][0]['published'], 13300)
            for name, target in [('prometheus', '/prometheus'), ('grafana', '/var/lib/grafana')]:
                service = services[name]
                self.assertEqual(service['image'], images[name]['reference'])
                self.assertEqual(service['volumes'], [{'type': 'bind', 'source': '/data/wb/' + name,
                                                      'target': target}])
                self.assertEqual(service['deploy']['placement']['constraints'],
                                 ['node.hostname == your-monitoring-worker'])
                self.assertEqual(service['deploy']['restart_policy']['condition'], 'on-failure')
                self.assertEqual(service['deploy']['update_config']['order'], 'stop-first')
                self.assertIn('healthcheck', service)
                self.assertNotIn('privileged', service)

    def test_monitoring_requires_explicit_paths_node_and_credentials(self):
        for missing in ('MONITORING_NODE', 'PROMETHEUS_DATA_DIR', 'GRAFANA_DATA_DIR',
                        'GRAFANA_USER', 'GRAFANA_PASSWORD'):
            settings = self.settings()
            del settings[missing]
            for runtime in ('headless', 'official'):
                result = self.render(runtime, settings)
                self.assertNotEqual(result.returncode, 0, missing)
                self.assertIn(missing, result.stderr)

    def test_embedded_config_survives_swarm_interpolation(self):
        for runtime in ('headless', 'official'):
            # --skip-interpolation on a second render must not be needed: check once-rendered command.
            result = self.render(runtime, self.settings())
            self.assertEqual(result.returncode, 0, result.stderr)
            services = yaml.safe_load(result.stdout)['services']
            for name in ('prometheus', 'grafana'):
                script = services[name]['command'][0]
                syntax = subprocess.run(['sh', '-n'], input=script, text=True, capture_output=True)
                self.assertEqual(syntax.returncode, 0, syntax.stderr)
            script = services['grafana']['command'][0]
            dashboard = json.loads(next(line for line in script.splitlines() if line.startswith('{"uid":')))
            # docker stack config re-escapes dollar signs for its YAML output.
            dashboard = json.loads(json.dumps(dashboard).replace('$$', '$'))
            expressions = [target['expr'] for panel in dashboard['panels'] for target in panel.get('targets', [])]
            self.assertTrue(any('$__rate_interval' in expr for expr in expressions))
            self.assertTrue(any('$runtime' in expr for expr in expressions))
            self.assertFalse(any('or vector(0)' in expr for expr in expressions))
            self.assertEqual(dashboard['uid'], 'wiremock-direct')
            self.assertEqual(dashboard['templating']['list'][0]['query'], runtime)
            self.assertNotIn('Capture outbox pending events', [p['title'] for p in dashboard['panels']])
            self.assertEqual(len({p['id'] for p in dashboard['panels']}), len(dashboard['panels']))
            prometheus = services['prometheus']['command'][0]
            config = yaml.safe_load(prometheus.split("<<'WIREMOCK_CONFIG_0'\n", 1)[1]
                                    .split('\nWIREMOCK_CONFIG_0', 1)[0])
            self.assertEqual(len(config['scrape_configs']), 3)
            self.assertEqual(config['scrape_configs'][0]['static_configs'][0]['targets'], [runtime + ':8081'])


if __name__ == '__main__':
    unittest.main()
