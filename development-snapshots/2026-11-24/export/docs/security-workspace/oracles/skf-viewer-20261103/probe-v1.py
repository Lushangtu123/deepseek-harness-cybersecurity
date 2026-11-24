"""Fixed SKF /viewer benign expression oracle. Run only inside the dedicated container."""
from pathlib import Path
import hashlib,importlib.util,importlib.metadata,json,os,sys
assert sys.platform=='linux' and os.geteuid()==1000 and Path('/.dockerenv').is_file()
assert all(not Path(p).exists() for p in ['/home/purge/.ssh','/home/purge/.dsh-improved','/var/run/docker.sock'])
sys.path.insert(0,'/deps')
plan=json.loads(Path('/protocol.json').read_text())
status=dict(row.split(':',1) for row in Path('/proc/self/status').read_text().splitlines() if ':' in row)
assert status['CapEff'].strip()=='0000000000000000' and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456'
assert Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert set(os.listdir('/sys/class/net'))=={'lo'}
try:Path('/src/original/SHOULD_NOT_WRITE').write_text('x');raise AssertionError('Source writable')
except OSError:pass
observations=[]
for variant in ['original','fixed-control']:
 root=Path('/src')/variant;os.chdir(root)
 source=root/'CMD2.py';raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==plan['sources'][variant]
 spec=importlib.util.spec_from_file_location('skf_'+variant.replace('-','_'),source)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module.app.config.update(TESTING=True)
 client=module.app.test_client()
 for item in plan['requests']:
  reached=[]
  def trace(frame,event,arg):
   caller=frame.f_back
   if event=='call' and frame.f_code.co_filename=='<string>' and caller and caller.f_code.co_filename==str(source):
    reached.append({'line':caller.f_lineno,'kind':'python-eval-frame'})
   return trace
  sys.settrace(trace)
  try:response=client.get('/viewer',query_string={} if item['value'] is None else {'lines':item['value']})
  finally:sys.settrace(None)
  body=response.get_data(as_text=True)
  row={'variant':variant,'requestId':item['id'],'statusCode':response.status_code,'evalFrames':reached,'responseSha256':hashlib.sha256(response.data).hexdigest(),'expectedMarkerPresent':item.get('marker') in body if 'marker' in item else None,'normalLogPresent':'oracle-alpha' in body}
  assert response.status_code==200
  if item['kind']=='normal':assert row['normalLogPresent']
  elif variant=='original':assert row['expectedMarkerPresent'] and reached and all(e['line']==plan['sinkLine'] for e in reached)
  else:assert not row['expectedMarkerPresent'] and not reached and row['normalLogPresent']
  observations.append(row)
print(json.dumps({'ok':True,'protocolSha256':hashlib.sha256(Path('/protocol.json').read_bytes()).hexdigest(),'python':sys.version.split()[0],'dependencies':{n:importlib.metadata.version(n) for n in plan['dependencies']},'conditions':{'realFlaskTestClient':True,'liveListenerStarted':False,'upstreamSourceUnmodified':True,'fixedControlIsAuthored':True,'oldRequirementsReproduced':False,'sourceReadonly':True,'networkNone':True,'nonRoot':True,'noCapabilities':True,'noNewPrivileges':True,'seccompEnabled':True,'sourceIdentityMatched':True,'uid':os.geteuid()},'observations':observations}))
