"""Guard evidence accounting and snapshot loading; no VM or SSH execution."""
import copy, hashlib, importlib.util, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Evidence(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'admission.py'
        self.assertTrue(path.exists(), 'Missing admission evidence implementation')
        spec = importlib.util.spec_from_file_location('admission_tested', path)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def trial(self, mode='unqueued', block=0):
        clients = [dict(index=i, connected=True, complete=True,
                        commandCalls=1, returncode=0) for i in range(6)]
        return dict(block=block, mode=mode, clients=clients,
                    workersReaped=True, serverStopped=True)

    def test_counts_failures_even_without_socket_exception(self):
        row = self.trial()
        row['clients'][0].update(complete=False, errorStage='reply',
                                  errorType='EOF', returncode=1)
        rows = self.m.summarize([row])
        self.assertEqual(rows[0]['clients'], 6)
        self.assertEqual(rows[0]['complete'], 5)
        self.assertEqual(rows[0]['failed'], 1)
        self.assertEqual(rows[0]['errors'], {'reply|EOF|None': 1})

    def test_missing_or_duplicate_worker_is_rejected(self):
        for kind in ['missing', 'duplicate']:
            row = self.trial()
            if kind == 'missing': row['clients'].pop()
            else: row['clients'][-1]['index'] = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.m.summarize([row])

    def test_inconsistent_success_or_replayed_request_is_rejected(self):
        for update in [dict(connected=False), dict(errorType='OSError'),
                       dict(commandCalls=2), dict(returncode=1)]:
            row = self.trial(); row['clients'][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.m.summarize([row])

    def test_duplicate_condition_block_or_unclean_workers_is_rejected(self):
        row = self.trial()
        with self.assertRaises(ValueError): self.m.summarize([row, copy.deepcopy(row)])
        for key in ['workersReaped', 'serverStopped']:
            bad = self.trial(); bad[key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.m.summarize([bad])

    def test_wrong_snapshot_digest_cannot_execute_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'payload.py'; sentinel = Path(temp) / 'ran'
            source.write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
            with self.assertRaises(ValueError): self.m.load_manager(source, '0' * 64)
            self.assertFalse(sentinel.exists())

    def test_valid_snapshot_executes_exact_verified_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'example.py'; raw = b'ANSWER=42\n'
            source.write_bytes(raw)
            loaded = self.m.load_manager(source, hashlib.sha256(raw).hexdigest())
            self.assertEqual(loaded.ANSWER, 42)

    def test_process_deadline_records_cancel_for_safe_cleanup(self):
        self.m.expire(14, None)
        self.assertTrue(self.m.pending_cancellation())
        with self.assertRaises(TimeoutError): self.m.check_cancel()

    def test_schedule_has_each_mode_once_per_block(self):
        rows = self.m.schedule()
        self.assertEqual(len(rows), 8)
        for block in range(4):
            self.assertEqual(sorted(r['mode'] for r in rows if r['block'] == block),
                             ['existing-queue', 'unqueued'])


if __name__ == '__main__': unittest.main()
