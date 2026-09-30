import unittest
from stage_timing import stages, distribution


class StageTimingTest(unittest.TestCase):
    def record(self):
        return {
            'offered_at': '2026-09-30T00:00:00Z',
            'hops': [
                {'service': 'generator-0', 'received_at': '2026-09-30T00:00:00Z', 'processed_at': '2026-09-30T00:00:01Z'},
                {'service': 'processor-0', 'received_at': '2026-09-30T00:00:03Z', 'processed_at': '2026-09-30T00:00:10Z'},
                {'service': 'evidence', 'received_at': '2026-09-30T00:00:14Z', 'processed_at': None}],
            'collected_at': '2026-09-30T00:00:15Z',
            'http_header_duration_ms': 6100,
            'processor_pacing_ms': 5,
        }

    def test_separates_queue_processing_and_evidence(self):
        completed, collected, durations = stages(self.record())
        self.assertEqual(collected - completed, 5)
        self.assertEqual(durations, {'beforeProcessorMs': 3000, 'processorMs': 7000,
                         'afterProcessorMs': 5000, 'httpHeaderMs': 6100, 'processorPacingMs': 5})

    def test_missing_or_ambiguous_processor_is_rejected(self):
        for hops in [[], [self.record()['hops'][1]] * 2]:
            with self.subTest(hops=hops), self.assertRaises(ValueError):
                stages({**self.record(), 'hops': hops})

    def test_clock_inconsistency_is_rejected(self):
        with self.assertRaises(ValueError):
            stages({**self.record(), 'collected_at': '2026-09-30T00:00:09Z'})

    def test_histogram_quantiles_weight_counts(self):
        self.assertEqual(distribution({6: 99, 100: 1}), {'count': 100, 'p50': 6, 'p99': 6, 'max': 100})


if __name__ == '__main__':
    unittest.main()
