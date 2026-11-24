from pathlib import Path
from hashlib import sha256
import ast,base64,json,os,shutil,sqlite3,subprocess,traceback
root=Path(__file__).resolve().parent
payload=json.loads((root/'input.json').read_bytes())
def save(value):
 p=root/'status.tmp';p.write_text(json.dumps(value));p.replace(root/'status.json')
save({'state':'running'})
try:
 assert os.geteuid()==1000
 for name,encoded in payload['files'].items():
  p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(encoded));assert sha256(p.read_bytes()).hexdigest()==payload['checks'][name]
 home=Path('/home/purge');daily=home/'.dsh-improved';installed=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/harness-improved-runtime/node_modules'
 exec(compile(payload['identityCode'],'<fixed-identity>','exec'))
 before=identity()
 outputs={}
 cases=[('gate',[str(home/'.local/node/bin/node'),'--test',str(root/'work/harness-purge-improved/tests/review-quality-gate.test.mjs')],35),('python',['/usr/bin/python3','-I','-B',str(root/'scripts/reviewer_snapshot.test.py')],35),('storage',['/usr/bin/python3','-I','-B',str(root/'scripts/reviewer_storage.test.py')],35),('archive',['/usr/bin/python3','-I','-B',str(root/'scripts/reviewer_archive.test.py')],35),('batch',['/usr/bin/python3','-I','-B',str(root/'scripts/eval_evidence_batch.test.py')],20),('normal',['/usr/bin/python3','-I','-B',str(root/'normal-live.py')],60),('storage-live',['/usr/bin/python3','-I','-B',str(root/'storage-live.py')],90)]
 for label,argv,seconds in cases:
  save({'state':'running','phase':label})
  run=subprocess.run(argv,cwd=root,env={**os.environ,'NODE_OPTIONS':''},stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=seconds)
  (root/(label+'.stdout')).write_text(run.stdout);(root/(label+'.stderr')).write_text(run.stderr)
  outputs[label]={'exitCode':run.returncode,'stdout':run.stdout,'stderr':run.stderr}
  if run.returncode:raise ValueError(label+' failed: '+run.stderr[-2500:])
 assert all(sha256((root/name).read_bytes()).hexdigest()==want for name,want in payload['checks'].items())
 assert identity()==before
 result={'state':'completed','outputs':outputs,'sourceSha256':payload['checks'],'dailyProgramFilesMatched':len(before['program']),'dailyDatabasesLogicallyMatched':len(before['databases']),'dailyConfigPinsRuntimeMatched':True}
 (root/'result.json').write_text(json.dumps(result));save({'state':'completed','resultSha256':sha256((root/'result.json').read_bytes()).hexdigest()})
except BaseException as error:
 save({'state':'failed','problem':type(error).__name__,'detail':str(error)[-3000:],'trace':traceback.format_exc()[-4000:],'scratchRetained':True})
