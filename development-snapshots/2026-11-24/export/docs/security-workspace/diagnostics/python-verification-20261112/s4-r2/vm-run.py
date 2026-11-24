from pathlib import Path
from hashlib import sha256
import ast,base64,importlib.util,json,sys,uuid
BASE=Path(__file__).resolve().parents[1];HERE=Path(__file__).resolve().parent;REPO=Path('exports/deepseek-harness-vm')
p=BASE/'vm-bridge.py';s=importlib.util.spec_from_file_location('b',p);b=importlib.util.module_from_spec(s);s.loader.exec_module(b)
def launch():
 assert not (HERE/'vm-intent.json').exists(),'Query existing task'
 source=(BASE/'s2/live-r4.py').read_text();prefix=source[:source.index("files['contracts.json']")];scope={'__file__':str(BASE/'s2/live-r4.py')};exec(compile(prefix,'fixed-local-prepare','exec'),scope)
 files={}
 for n,raw in scope['files'].items():
  if n.startswith('sources/'):files[n]=raw
  elif n.startswith('dependencies/'):files['vendor/'+n.removeprefix('dependencies/')]=raw
  elif n.startswith('code/') and not n.endswith('python_execution_verify.py'):files['modules/'+n.removeprefix('code/')]=raw
 files['contracts.json']=json.dumps(scope['contracts']).encode();files['historical-dataset.json']=json.dumps(scope['data']).encode();files['dependency-lock.json']=(BASE/'dependencies/lock.json').read_bytes()
 for n in ['reviewer_snapshot.py','reviewer_storage.py','verifier_snapshot.py','python_execution_verify.py','review_quality_gate.mjs','verifier-dependencies.lock.json']:files['scripts/'+n]=(REPO/'scripts'/n).read_bytes()
 for name,path in {'baseline-rules.json':'work/harness-purge-improved/security-rules.json','candidate-rules.json':'docs/security-workspace/ordinary-rules-combined.candidate.json','policy.json':'docs/security-workspace/review-quality-policy.candidate.json','ledger.json':'docs/security-workspace/review-sample-ledger.json'}.items():files[name]=(REPO/path).read_bytes()
 source=(BASE.parent/'harness-workspace-bootstrap-20261110/stage-guest.py').read_text();functions=[ast.get_source_segment(source,n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in {'identity','digest'}];files['identity-code.py']='\n\n'.join(functions).encode();files['score.mjs']=(HERE/'score.mjs').read_bytes()
 payload=json.dumps({'checks':{n:sha256(raw).hexdigest() for n,raw in files.items()},'files':{n:base64.b64encode(raw).decode() for n,raw in files.items()}});worker=(HERE/'vm-worker.py').read_text();remote='/home/purge/.cache/verify-execution-acceptance-'+uuid.uuid4().hex[:10]
 intent={'remoteRoot':remote,'files':json.loads(payload)['checks'],'workerSha256':sha256(worker.encode()).hexdigest(),'payloadSha256':sha256(payload.encode()).hexdigest()};(HERE/'vm-intent.json').write_text(json.dumps(intent,indent=2)+'\n');(HERE/'vm-input.json').write_text(payload)
 script='from pathlib import Path\nimport os,subprocess,json\nos.umask(0o077)\nroot=Path('+repr(remote)+');root.mkdir(mode=0o700)\n(root/"input.json").write_text('+repr(payload)+')\n(root/"worker.py").write_text('+repr(worker)+')\n'+'''with (root/'stdout').open('wb') as out,(root/'stderr').open('wb') as err:p=subprocess.Popen(['/usr/bin/timeout','--kill-after=5','480','/usr/bin/python3','-I','-B',str(root/'worker.py')],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
print(json.dumps({'pid':p.pid,'state':'submitted'}))'''
 print(json.dumps(b.call(script,40)))
def poll():
 v=json.loads((HERE/'vm-intent.json').read_bytes());script='from pathlib import Path\nimport json\np=Path('+repr(v['remoteRoot'])+')/"result.json"\nprint(p.read_text() if p.exists() else json.dumps({"state":"running"}))';result=b.call(script,30)
 if result['state']=='completed':
  assert result['sourcesVerified']==v['files']
  (HERE/'vm-result.json').write_text(json.dumps(result,indent=2)+'\n')
  for n,raw in result['artifacts'].items():
   assert sha256(raw.encode()).hexdigest()==result['artifactSha256'][n];p=HERE/'guest-evidence'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(raw)
  print(json.dumps({k:result[k] for k in ['state','dailyProgramFilesMatched','dailyDatabasesMatched']}))
 else:print(json.dumps(result))
 (HERE/'vm-poll.json').write_text(json.dumps({k:v for k,v in result.items() if k not in {'artifacts','sourcesVerified'}},indent=2)+'\n')
{'launch':launch,'poll':poll}[sys.argv[1]]()
