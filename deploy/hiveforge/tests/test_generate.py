"""Check lab projection parity, explicit input failure and generated-file drift."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hiveforge_generate', ROOT / 'generate.py')
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class HiveForgeLabTest(unittest.TestCase):
    def test_projection_matches_canonical_swarm_stack(self):
        settings = {
            'LAB_NODE': 'test-node', 'CAPTURE_PREFIX': 'test-capture',
            'RABBIT_PASSWORD': 'benchmark', 'GRAFANA_PASSWORD': 'benchmark',
        }
        # Ambient Portainer overrides must not change this fixed profile test.
        env = {key: value for key, value in os.environ.items()
               if key not in {match[0] for match in generate.VARIABLE.findall(generate.SOURCE.read_text())}}
        env.update(settings)
        text = generate.template(generate.SOURCE.read_text())
        text = Environment(undefined=StrictUndefined).from_string(text).render(
            lab_node=settings['LAB_NODE'], capture_prefix=settings['CAPTURE_PREFIX'],
            active_runtime='both')
        with tempfile.TemporaryDirectory() as directory:
            rendered = Path(directory) / 'compose.yml'
            rendered.write_text(text)
            def parsed(path):
                result = subprocess.run(['docker', 'stack', 'config', '-c', str(path)],
                                        env=env, capture_output=True, text=True, check=True)
                return yaml.safe_load(result.stdout)
            self.assertEqual(parsed(rendered), parsed(generate.SOURCE))
        stack = yaml.safe_load(text)
        self.assertEqual(len(stack['services']), 7)
        self.assertNotIn('secrets', stack)
        self.assertFalse(any('secrets' in service for service in stack['services'].values()))

    def test_single_runtime_changes_only_mock_replica_counts(self):
        template = Environment(undefined=StrictUndefined).from_string(
            generate.template(generate.SOURCE.read_text()))
        def render(selection):
            return yaml.safe_load(template.render(lab_node='test-node',
                                  capture_prefix='test-capture', active_runtime=selection))
        baseline = render('both')
        for active, inactive in [('official', 'headless'), ('headless', 'official')]:
            with self.subTest(active=active):
                stack = render(active)
                self.assertEqual(stack['services'][active]['deploy']['replicas'], 1)
                self.assertEqual(stack['services'][inactive]['deploy']['replicas'], 0)
                stack['services'][inactive]['deploy']['replicas'] = 1
                self.assertEqual(stack, baseline)

    def test_unknown_required_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UNDECLARED'):
            generate.template('services: {example: {image: "${UNDECLARED:?required}"}}')

    def test_checked_in_template_matches_generator(self):
        self.assertEqual(generate.TARGET.read_text(), generate.template(generate.SOURCE.read_text()))


if __name__ == '__main__':
    unittest.main()
