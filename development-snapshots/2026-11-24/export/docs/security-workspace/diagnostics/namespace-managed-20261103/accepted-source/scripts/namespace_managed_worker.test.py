import ast,base64,json,subprocess,sys,unittest
from pathlib import Path
from hashlib import sha256
WORKER=Path(__file__).with_name('python_namespace_review.py')
RULE='policy.harness.python.dynamic-code-namespace'
def payload(source):
 raw=source.encode();n=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='eval');starts=[0]+[i+1 for i,b in enumerate(raw) if b==10]
 return {'files':{'app.py':{'base64':base64.b64encode(raw).decode(),'sha256':sha256(raw).hexdigest()}},'results':[{'check_id':RULE,'path':'app.py','start':{'line':n.lineno,'col':n.col_offset+1,'offset':starts[n.lineno-1]+n.col_offset},'end':{'line':n.end_lineno,'col':n.end_col_offset+1,'offset':starts[n.end_lineno-1]+n.end_col_offset}}]}
class ManagedWorker(unittest.TestCase):
 def runworker(self,p):return subprocess.run([sys.executable,'-I','-B',str(WORKER),'--managed'],input=json.dumps(p),capture_output=True,text=True,timeout=7)
 def test_managed_input_is_ast_only_and_never_executes_top_level(self):
  p=payload('raise RuntimeError("must never execute source")\ndef run(value):\n    return eval(value, {})\n');r=self.runworker(p);self.assertEqual(r.returncode,0,r.stderr);v=json.loads(r.stdout);self.assertEqual(len(v['observations']),1);self.assertEqual(v['observations'][0]['disposition'],'unverified')
 def test_wrong_digest_and_surplus_metadata_are_rejected(self):
  for mutate in [lambda p:p['files']['app.py'].update(sha256='a'*64),lambda p:p.update(extra='x'),lambda p:p['files']['app.py'].update(path='/etc/passwd')]:
   p=payload('eval("6*7", {})\n');mutate(p);self.assertNotEqual(self.runworker(p).returncode,0)
 def test_unmatched_full_anchor_remains_partial(self):
  p=payload('eval("6*7", {})\n');p['results'][0]['start']['offset']+=1;r=self.runworker(p);self.assertEqual(r.returncode,0,r.stderr);v=json.loads(r.stdout);self.assertEqual(v['state'],'partial');self.assertEqual(len(v['unmatchedAnchors']),1)
if __name__=='__main__':unittest.main()
