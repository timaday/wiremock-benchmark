"""Validate deployable upstream-only isolation and Nginx interpolation."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parent


class UpstreamFiveTest(unittest.TestCase):
    def settings(self):
        return dict(os.environ, NGINX_NODE='proxy-worker',
                    **{f'WIREMOCK_{i}_NODE': f'worker-{i}' for i in range(1, 6)})

    def test_deployable_routes_and_extension_free_instances(self):
        result = subprocess.run(['docker', 'stack', 'config', '-c',
                                 str(ROOT/'stack-official-five.yml')],
                                env=self.settings(), text=True, capture_output=True, check=True)
        services = yaml.safe_load(result.stdout)['services']
        self.assertEqual(len(services), 6)
        for i in range(1, 6):
            service = services[f'wiremock-{i}']
            self.assertTrue(service['image'].startswith('wiremock/wiremock:3.13.2@sha256:'))
            self.assertNotIn('--extensions', service['command'])
            self.assertEqual(set(service['environment']), {'JAVA_TOOL_OPTIONS'})
            self.assertEqual(service['ports'][0]['published'], 19000+i)
            self.assertEqual(service['deploy']['placement']['constraints'],
                             [f'node.hostname == worker-{i}'])
            self.assertTrue(all(mount['type'] == 'tmpfs' for mount in service['volumes']))
        self.assertEqual(services['nginx']['ports'][0]['published'], 19081)
        self.assertIn('proxy_next_upstream off;', services['nginx']['command'][0])

    def test_nginx_variables_survive_compose_interpolation(self):
        result = subprocess.run(['docker', 'compose', '-f',
                                 str(ROOT/'stack-official-five.yml'), 'config', '--format', 'json'],
                                env=self.settings(), text=True, capture_output=True, check=True)
        script = json.loads(result.stdout)['services']['nginx']['command'][0]
        # Compose config may re-escape dollars for a subsequent render.
        script = script.replace('$$', '$')
        for variable in ('$http_host', '$proxy_add_x_forwarded_for', '$scheme', '$is_args$args'):
            self.assertIn(variable, script)
        self.assertNotIn('variable is not set', result.stderr)
        syntax = subprocess.run(['sh', '-n'], input=script, text=True, capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_missing_node_fails_configuration(self):
        for variable in ['NGINX_NODE'] + [f'WIREMOCK_{i}_NODE' for i in range(1, 6)]:
            env = self.settings()
            del env[variable]
            result = subprocess.run(['docker', 'stack', 'config', '-c',
                                     str(ROOT/'stack-official-five.yml')],
                                    env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(variable, result.stderr)


if __name__ == '__main__':
    unittest.main()
