from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import sys
from pathlib import Path as ModulePath

sys.path.insert(0, str(ModulePath(__file__).resolve().parents[1] / 'work/harness-purge-improved/package/scripts'))

from eval_evidence_batch import review_batch

CALLER = '''from flask import request
from evaluator import run
def direct():
    value = request.args.get("value")
    if value in ("foo", "bar"):
        return eval(value)
def indirect():
    value = request.args.get("value")
    return run(value)
'''
CALLEE = 'def run(value):\n    return exec(value)\n'


class BatchTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.files = {'routes.py': CALLER, 'evaluator.py': CALLEE}
        for name, source in self.files.items():
            (self.root / name).write_text(source)
        self.manifest = {
            'files': {name: sha256(source.encode()).hexdigest() for name, source in self.files.items()},
            'imports': [{'caller':'routes.py', 'callee':'evaluator.py', 'line':9}],
        }
        self.scan = {'results': [{'check_id':'policy.harness.python.eval', 'path':'/src/routes.py', 'start':{'line':6}}]}

    def test_association_and_separate_observations(self):
        report = review_batch(self.root, self.manifest, self.scan)
        guard, = report['guardEvidence']
        imported, = report['importEvidence']
        self.assertEqual(guard['finding'], {'rule':'policy.harness.python.eval','file':'routes.py','line':6})
        self.assertEqual((imported['callerFile'], imported['calleeFile'], imported['sinkLine']), ('routes.py','evaluator.py',2))
        self.assertEqual(guard['evidence']['disposition'], 'unverified')
        self.assertEqual(imported['disposition'], 'unverified')

    def test_auto_discovery_uses_only_pinned_siblings_and_deduplicates(self):
        self.manifest['discoverImports'] = True
        report = review_batch(self.root, self.manifest, self.scan)
        self.assertEqual(report['importChecks'], 1)
        self.assertEqual(report['discoveredImportChecks'], 1)
        self.manifest.pop('imports')
        report = review_batch(self.root, self.manifest, self.scan)
        self.assertEqual(report['importEvidence'][0]['callLine'], 9)
        self.manifest['files'].pop('evaluator.py')
        report = review_batch(self.root, self.manifest, self.scan)
        self.assertEqual(report['importChecks'], 0)
        self.assertEqual(report['importEvidence'], [])

    def test_auto_discovery_records_namespace_sink_without_fabricating_a_scanner_hit(self):
        import json
        for sink in ['eval', 'exec']:
            for namespaces in [', {}', ', {}, {}']:
                with self.subTest(sink=sink, namespaces=namespaces):
                    callee = 'def run(value):\n    return ' + sink + '(value' + namespaces + ')\n'
                    (self.root / 'evaluator.py').write_text(callee)
                    self.manifest['files']['evaluator.py'] = sha256(callee.encode()).hexdigest()
                    self.manifest['discoverImports'] = True
                    scan = {'results': []}
                    before = json.dumps(scan, sort_keys=True)
                    report = review_batch(self.root, self.manifest, scan)
                    self.assertEqual(report['discoveredImportChecks'], 1)
                    self.assertEqual(report['importChecks'], 1)
                    evidence, = report['importEvidence']
                    self.assertEqual(evidence['sourceLine'], 8)
                    self.assertEqual(evidence['callLine'], 9)
                    self.assertEqual(evidence['sinkLine'], 2)
                    self.assertEqual(evidence['sink'], sink)
                    self.assertEqual(evidence['disposition'], 'unverified')
                    self.assertEqual(report['guardEvidence'], [])
                    self.assertEqual(json.dumps(scan, sort_keys=True), before)

    def test_auto_discovery_rejects_invalid_option_and_excess_candidates(self):
        self.manifest['discoverImports'] = 'true'
        with self.assertRaisesRegex(ValueError, 'discovery'):
            review_batch(self.root, self.manifest, self.scan)
        self.manifest['discoverImports'] = True
        source = CALLER + ''.join(
            f'def route_{i}():\n    value = request.args.get("value")\n    return run(value)\n'
            for i in range(64)
        )
        (self.root / 'routes.py').write_text(source)
        self.manifest['files']['routes.py'] = sha256(source.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'import check limit'):
            review_batch(self.root, self.manifest, self.scan)

    def test_string_shape_evidence_keeps_original_scanner_anchor(self):
        source = """from flask import request
def route():
    value = request.args.get("value")
    if not value.startswith("'") or not value.endswith("'") or "'" in value[1:-1]:
        return "invalid"
    exec(value)
"""
        (self.root / 'routes.py').write_text(source)
        self.manifest['files']['routes.py'] = sha256(source.encode()).hexdigest()
        self.manifest['imports'] = []
        self.scan['results'] = [{'check_id':'policy.harness.python.exec','path':'/src/routes.py','start':{'line':6}}]
        report = review_batch(self.root,self.manifest,self.scan)
        row, = report['plainStringEvidence']
        self.assertEqual(row['finding']['line'],6)
        self.assertEqual(row['evidence']['executionLine'],6)
        self.assertEqual(row['evidence']['disposition'],'unverified')

    def test_mutation_fails_entire_batch(self):
        (self.root / 'evaluator.py').write_text('def run(value):\n    return value\n')
        with self.assertRaisesRegex(ValueError, 'digest'):
            review_batch(self.root, self.manifest, self.scan)

    def test_exec_finding_cannot_borrow_eval_guard(self):
        self.scan['results'][0]['check_id'] = 'policy.harness.python.exec'
        self.assertEqual(review_batch(self.root,self.manifest,self.scan)['guardEvidence'], [])

    def test_untrusted_scan_paths_never_read_files(self):
        for path in ('/src/../routes.py', '/etc/passwd', '/src/unlisted.py'):
            with self.subTest(path=path):
                self.scan['results'][0]['path'] = path
                self.assertEqual(review_batch(self.root, self.manifest, self.scan)['guardEvidence'], [])

    def test_symlink_and_duplicate_requests(self):
        self.manifest['imports'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            review_batch(self.root, self.manifest, self.scan)
        self.manifest['imports'].pop()
        (self.root / 'evaluator.py').unlink()
        (self.root / 'evaluator.py').symlink_to(self.root / 'routes.py')
        with self.assertRaises(ValueError):
            review_batch(self.root, self.manifest, self.scan)


if __name__ == '__main__':
    unittest.main()
