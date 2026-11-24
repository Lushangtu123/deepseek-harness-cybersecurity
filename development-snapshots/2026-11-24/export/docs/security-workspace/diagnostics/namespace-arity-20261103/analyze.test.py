"""Post-review binding regression checks, replayable against archived prior verifier."""
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import json, os, shutil, subprocess, unittest

w = Path(__file__).resolve().parent
repo = w.parents[1]/'exports/deepseek-harness-vm'
files = ['cases.json','intent.json','candidate-freeze.json','regression-freeze.json',
         'regression-cases.json','baseline-scan.json','combined19-scan.json',
         'arity17-scan.json','combined20-scan.json','arity17.candidate.json',
         'combined20.candidate.json','arity17-regression.json','combined20-regression.json',
         'native-oracle.json','protocol.json','protocol-provenance.json','probe.py','final-state.json']

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='namespace-binding-',dir='/tmp')
        root = Path(self.temporary.name)
        self.task = root/'work/experiment'; self.task.mkdir(parents=True)
        for name in files: shutil.copyfile(w/name,self.task/name)
        shutil.copyfile(w/os.environ.get('ARITY_ANALYZER','analyze.py'),self.task/'analyze.py')
        old = root/'work/harness-r3-combined-20261103';old.mkdir()
        for name in ['synthetic-baseline.json','synthetic-combined.json','owasp-baseline.json','owasp-combined.json','owasp-index.json']:
            shutil.copyfile(w.parent/'harness-r3-combined-20261103'/name,old/name)
        target = root/'exports/deepseek-harness-vm/docs/security-workspace';target.mkdir(parents=True)
        shutil.copyfile(repo/'docs/security-workspace/ordinary-calibration-cases.json',target/'ordinary-calibration-cases.json')
        self.old = old
    def tearDown(self): self.temporary.cleanup()
    def mutate(self,name,change,root=None):
        path = (root or self.task)/name;data = json.loads(path.read_text());change(data)
        path.write_text(json.dumps(data,indent=2)+'\n')
    def check(self,valid=False):
        p = subprocess.run(['python3','-B','analyze.py'],cwd=self.task,capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode==0,valid,p.stdout+'\n'+p.stderr)
    def added(self,r):
        return next(h for h in r['native']['result']['results'] if 'dynamic-code-namespace' in h['check_id'])
    def test_original_receipts_pass(self): self.check(True)
    def test_wrong_added_rule_same_count_and_file_fails(self):
        self.mutate('arity17-scan.json',lambda r:self.added(r).update(check_id='policy.unrelated'))
        self.check()
    def test_shifted_added_column_same_count_and_line_fails(self):
        self.mutate('arity17-scan.json',lambda r:self.added(r)['start'].update(col=99))
        self.check()
    def test_runtime_source_hash_cannot_differ_from_scan(self):
        self.mutate('protocol.json',lambda r:r['sources'].update({'plain-eval-2.py':'0'*64}))
        digest = sha256((self.task/'protocol.json').read_bytes()).hexdigest()
        self.mutate('native-oracle.json',lambda r:r['result'].update(protocolSha256=digest))
        # Keep the two self-declared runtime hashes consistent; source equality must still reject.
        self.mutate('native-oracle.json',lambda r:[o.update(sourceSha256='0'*64) for o in r['result']['observations'] if o['caseId']=='plain-eval-2'])
        self.check()
    def test_runtime_result_must_match_protocol(self):
        self.mutate('native-oracle.json',lambda r:r['result']['observations'][0].update(result=1))
        self.check()
    def test_failed_old_scan_cannot_be_preservation_reference(self):
        self.mutate('synthetic-baseline.json',lambda r:r.update(scannerExitCode=1),self.old)
        self.check()
    def test_missing_scanned_file_fails(self):
        self.mutate('combined20-scan.json',lambda r:r['native']['result']['paths']['scanned'].pop())
        self.check()
    def test_runtime_image_mismatch_fails(self):
        self.mutate('native-oracle.json',lambda r:r.update(imageId='sha256:'+'0'*64))
        self.check()
    def test_final_runtime_rule_hash_mismatch_fails(self):
        self.mutate('final-state.json',lambda r:r.update(rulesSha256='0'*64))
        self.check()
    def test_runtime_error_mismatch_fails(self):
        self.mutate('native-oracle.json',lambda r:r['result']['observations'][0].update(error='ValueError'))
        self.check()
    def test_runtime_frame_count_mismatch_fails(self):
        self.mutate('native-oracle.json',lambda r:r['result']['observations'][0].update(dynamicFrames=[]))
        self.check()
    def test_extra_regression_rule_cannot_hide_in_preservation(self):
        def extra(r):
            import copy
            hit = copy.deepcopy(r['native']['result']['results'][0]);hit['check_id']='policy.extra'
            r['native']['result']['results'].append(hit)
        self.mutate('arity17-regression.json',extra)
        self.check()

if __name__=='__main__': unittest.main()
