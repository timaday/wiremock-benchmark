"""Check lab projection parity, explicit input failure and generated-file drift."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

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
        text = text.replace('{{ lab_node }}', settings['LAB_NODE'])
        text = text.replace('{{ capture_prefix }}', settings['CAPTURE_PREFIX'])
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

    def test_unknown_required_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UNDECLARED'):
            generate.template('services: {example: {image: "${UNDECLARED:?required}"}}')

    def test_checked_in_template_matches_generator(self):
        self.assertEqual(generate.TARGET.read_text(), generate.template(generate.SOURCE.read_text()))


if __name__ == '__main__':
    unittest.main()
