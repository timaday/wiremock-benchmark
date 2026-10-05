"""Check transport boundaries and finite workload identity for fresh RabbitMQ bundles."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare import prepare


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
PROFILES = {
    'smoke': (1, 12, 20, 0),
    'load': (255, 22950, 20, 60),
    'diagnostic': (255, 68850, 60, 180),
    'endurance': (255, 940950, 60, 3600),
}


class PrepareRabbitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='wiremock-rabbit-prepare-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.bundles = []
        for runtime in ('official', 'headless'):
            for mode in PROFILES:
                bundle = prepare(REPO, Path(cls.directory.name) / f'{runtime}-{mode}', runtime, mode)
                cls.bundles.append((bundle, yaml.safe_load((bundle / 'scenario.yaml').read_text()),
                                    json.loads((bundle / 'benchmark.json').read_text())))

    def test_all_work_boundaries_match_previous_rabbit_configuration(self):
        reference = PACKAGE / 'hfm-rabbit-20261001/bundles/ph-wiremock-headless-smoke-84277a3c/scenario.yaml'
        workers = {bee['role']: bee['config'] for bee in json.loads(reference.read_text())['template']['bees']}
        for _, scenario, manifest in self.bundles:
            with self.subTest(runtime=manifest['runtime'], mode=manifest['mode']):
                self.assertEqual(manifest['workTransport'], 'RABBITMQ')
                self.assertEqual(len(scenario['template']['bees']), 9)
                boundaries = 0
                for bee in scenario['template']['bees']:
                    for direction in ('inputs', 'outputs'):
                        adapter = bee['config'][direction]
                        if adapter['type'] in ('CSV_DATASET', 'REDIS'):
                            continue
                        self.assertEqual(adapter, workers[bee['role']][direction])
                        self.assertEqual(adapter['type'], 'RABBITMQ')
                        boundaries += 1
                self.assertEqual(boundaries, 13)
                self.assertNotIn('ARTEMIS', json.dumps(scenario))
                self.assertNotIn('consumerWindowBytes', json.dumps(scenario))

    def test_source_target_and_evidence_boundaries_are_preserved(self):
        for bundle, scenario, manifest in self.bundles:
            rate, _, warmup, measurement = PROFILES[manifest['mode']]
            with self.subTest(bundle=bundle.name):
                self.assertEqual(manifest['offeredRate'], rate * 4)
                self.assertEqual((manifest['warmupSeconds'], manifest['measurementSeconds']),
                                 (warmup, measurement))
                self.assertEqual({case['delay'] for case in manifest['cases']}, {6000})
                self.assertEqual({case['size'] for case in manifest['cases']}, {1024, 5120, 10240, 51200})
                self.assertEqual({case['template'] for case in manifest['cases']}, {'static', 'json', 'text'})
                for bee in scenario['template']['bees']:
                    config = bee['config']
                    if bee['role'].startswith('generator-'):
                        self.assertEqual(config['inputs']['type'], 'CSV_DATASET')
                        self.assertEqual(config['inputs']['csv']['ratePerSec'], rate)
                        self.assertFalse(config['inputs']['csv']['rotate'])
                    elif bee['role'].startswith('processor-'):
                        self.assertEqual(config['baseUrl'], "{{ sut.endpoints['default'].baseUrl }}")
                        self.assertEqual(config['connectionReuse'], 'PER_THREAD')
                        self.assertEqual(config['timeoutMs'], 30000)
                        self.assertEqual(config['threadCount'], 16 if manifest['mode'] == 'smoke' else 1800)
                    else:
                        self.assertEqual(bee['role'], 'evidence')
                        self.assertEqual(config['outputs']['type'], 'REDIS')
                        self.assertEqual(config['outputs']['redis']['defaultList'], 'wmb.' + manifest['runId'])
                sut = yaml.safe_load((bundle / 'sut' / manifest['runtime'] / 'sut.yaml').read_text())
                self.assertEqual(sut['endpoints']['default']['baseUrl'],
                                 f"http://wmb-ph-{manifest['runtime']}:8080")

    def test_datasets_keep_every_expected_request_and_case_in_order(self):
        for bundle, _, manifest in self.bundles:
            rows_per_lane = PROFILES[manifest['mode']][1]
            shared = manifest['mode'] == 'endurance'
            files = sorted((bundle / 'datasets').glob('*.csv'))
            with self.subTest(bundle=bundle.name):
                self.assertEqual(len(files), 1 if shared else 4)
                self.assertEqual(manifest['expectedRequests'], rows_per_lane * 4)
                for lane, file in enumerate(files):
                    with file.open(newline='') as stream:
                        reader = csv.DictReader(stream)
                        count = 0
                        for sequence, row in enumerate(reader):
                            case = manifest['cases'][sequence % len(manifest['cases'])]
                            expected_id = (f'{sequence:010d}' if shared else
                                           f"{manifest['runId']}-{lane:02d}{sequence:010d}")
                            self.assertEqual(row, {
                                'sequence' if shared else 'benchId': expected_id,
                                'caseId': case['id'], 'size': str(case['size']),
                            })
                            count += 1
                    self.assertEqual(count, rows_per_lane)

    def test_preparations_have_distinct_run_and_scenario_ids(self):
        self.assertEqual(len({m['runId'] for _, _, m in self.bundles}), len(self.bundles))
        self.assertEqual(len({s['id'] for _, s, _ in self.bundles}), len(self.bundles))


if __name__ == '__main__':
    unittest.main()
