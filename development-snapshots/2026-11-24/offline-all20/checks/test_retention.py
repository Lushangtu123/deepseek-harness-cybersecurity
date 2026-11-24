"""Independent no-process fixture: exercise the actual public-check function."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util, json, os, sys, unittest
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
BASE = R.parent / 'harness-full20-host-20261122/candidate/checks/run_consumer_closure_checks.py'
SOURCE = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else BASE

def load():
    spec = importlib.util.spec_from_file_location('retention_subject', SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class Retention(unittest.TestCase):
    def exercise(self, scenario):
        mod = load()
        root = R / 'checks/tmp' / ('retention-' + os.urandom(5).hex())
        root.mkdir(parents=True)
        mod.ROOT = root
        box = root / 'checks/tmp/closure-public-compile-unit'
        box.mkdir(parents=True)
        journal = box / 'preflight/evidence/unit/process-client-identity.json'
        journal.parent.mkdir(parents=True)
        journal.write_text('{"pid":123,"identity":null,"unitOnly":true}\n')
        original = journal.read_bytes()
        class FakeBox:
            path = box
            def write_preflight_license(self): pass
            def preflight(self):
                return SimpleNamespace(returncode=79 if scenario=='preflight-failure' else 0,
                                       stderr='preflight: synthetic-unknown-identity')
            def write_formal_admission(self, **kw): pass
            def prepare(self):
                if scenario=='prepare-exception': raise RuntimeError('synthetic-prepare-failure')
            def write_json(self, p, obj):
                p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj))
            def run(self, args):
                return SimpleNamespace(returncode=3,stderr='runner: known-record-state')
        with patch.object(mod.regression_lib,'Sandbox',lambda *a,**kw:FakeBox()):
            try: answer=mod.public_compile_diagnostic(None,None)
            except (AssertionError,RuntimeError): answer=None
        self.assertTrue(journal.is_file(),'original inner identity journal was deleted')
        self.assertEqual(journal.read_bytes(),original)
        if scenario=='successful-assertion':self.assertTrue(answer[0])
        if hasattr(mod,'RETAINED_SANDBOXES'):
            self.assertIn({'caseId':'public-compile-known-failure-is-diagnostic-3',
                           'relativePath':str(box.relative_to(root))},mod.RETAINED_SANDBOXES)

    def test_preflight_failure_preserves_identity(self):self.exercise('preflight-failure')
    def test_prepare_exception_preserves_identity(self):self.exercise('prepare-exception')
    def test_success_preserves_identity(self):self.exercise('successful-assertion')

if __name__=='__main__':unittest.main(verbosity=2)
