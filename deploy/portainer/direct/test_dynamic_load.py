"""Negative controls for the demonstration's client/archive oracle."""
import base64
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location('dynamic_load', Path(__file__).with_name('dynamic-load.py'))
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


class ReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'archive').mkdir()
        self.phase = self.root / 'hold'
        self.phase.mkdir()
        (self.phase / 'started-ms.txt').write_text('0')
        request = b'{"requestId":"client-1"}'
        digest = lambda body: hashlib.sha256(body).hexdigest()
        with (self.phase / 'clients.csv').open('w') as output:
            writer = csv.writer(output)
            writer.writerow(['id', 'startedMs', 'completedMs', 'elapsedMs', 'success', 'bytes',
                             'requestSha256', 'responseSha256'])
            writer.writerow(['client-1', 45000, 46000, 1000, 'true', len(request), digest(request), digest(b'')])
        with sqlite3.connect(self.root / 'archive/events.db') as db:
            db.execute('CREATE TABLE events(run_id,request_id,phase,body_bytes,body_sha256,payload_zlib)')
            for phase in ('REQUEST', 'RESPONSE_PREPARED', 'SEND_COMPLETED'):
                body = request if phase == 'REQUEST' else b''
                event = {'schemaVersion': 2, 'runId': 'run', 'requestId': 'internal-1',
                         'correlationId': 'client-1', 'correlationStatus': 'PRESENT', 'phase': phase,
                         'method': 'POST', 'url': '/transaction', 'status': 200,
                         'headers': {}, 'bodyBase64': base64.b64encode(body).decode()}
                db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                           ('run', 'internal-1', phase, len(body), digest(body),
                            zlib.compress(json.dumps(event).encode())))

    def reconcile(self, delay_ms=1000):
        # Missing evidence must fail immediately in these negative controls.
        with patch.object(load.harness, 'wait_for', lambda check, seconds: check()):
            return load.reconcile(self.root, 'run', self.phase, delay_ms)

    def test_one_second_response_fails_six_second_check(self):
        with self.assertRaisesRegex(AssertionError, 'before configured delay'):
            self.reconcile(delay_ms=6000)

    def test_complete(self):
        result = self.reconcile()
        self.assertEqual((result['requests'], result['events']), (1, 3))

    def test_missing_phase_rejected(self):
        with sqlite3.connect(self.root / 'archive/events.db') as db:
            db.execute("DELETE FROM events WHERE phase='SEND_COMPLETED'")
        with self.assertRaises(AssertionError):
            self.reconcile()

    def test_duplicate_phase_rejected(self):
        with sqlite3.connect(self.root / 'archive/events.db') as db:
            db.execute("INSERT INTO events SELECT * FROM events WHERE phase='REQUEST'")
        with self.assertRaises(AssertionError):
            self.reconcile()

    def test_corrupt_body_hash_rejected(self):
        with sqlite3.connect(self.root / 'archive/events.db') as db:
            db.execute("UPDATE events SET body_sha256='wrong' WHERE phase='REQUEST'")
        with self.assertRaises(AssertionError):
            self.reconcile()


if __name__ == '__main__':
    unittest.main()
