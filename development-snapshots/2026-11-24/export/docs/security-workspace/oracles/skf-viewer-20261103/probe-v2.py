"""Strengthened fixed SKF oracle; only inside the dedicated diagnostic container."""
from pathlib import Path
import hashlib,importlib.util,importlib.metadata,importlib,json,os,sys
assert sys.platform=='linux' and os.geteuid()==65534 and Path('/.dockerenv').is_file()
assert all(not Path(p).exists() for p in ['/home/purge/.ssh','/home/purge/.dsh-improved','/var/run/docker.sock'])
sys.path.insert(0,'/deps')
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
plan=json.loads(Path('/protocol.json').read_text());measured_probe=sha('/probe.py');assert measured_probe==plan['probeSha256']
for path,expected in plan['inputFiles'].items():assert sha(path)==expected
entries={str(p.relative_to('/deps')):sha(p) for p in sorted(Path('/deps').rglob('*')) if p.is_file()}
assert hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()==plan['dependencyTreeSha256']
original=Path('/src/original/CMD2.py').read_bytes();fixed=Path('/src/fixed-control/CMD2.py').read_bytes()
assert hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()==plan['gitBlobSha1']
left=original.decode().splitlines();right=fixed.decode().splitlines();assert len(left)==len(right)
assert [i for i,(a,b) in enumerate(zip(left,right),1) if a!=b]==[plan['sinkLine']]
assert right[plan['sinkLine']-1]==left[plan['sinkLine']-1].replace(plan['oldExpression'],plan['fixedExpression'])
status=dict(row.split(':',1) for row in Path('/proc/self/status').read_text().splitlines() if ':' in row)
assert status['CapEff'].strip()=='0000000000000000' and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456' and Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert set(os.listdir('/sys/class/net'))=={'lo'}
mounts={line.split()[4]:line.split()[5].split(',') for line in Path('/proc/self/mountinfo').read_text().splitlines()}
assert all('ro' in mounts[path] for path in ['/','/src','/deps'])
write_failures={}
for directory in ['/src/original','/src/fixed-control','/deps','/']:
 try:Path(directory,'ORACLE_NO_WRITE').write_text('x');raise AssertionError('Readonly target writable')
 except OSError as error:write_failures[directory]=error.errno

def listeners():
 return sum(1 for name in ['tcp','tcp6'] if (p:=Path('/proc/net')/name).exists() for line in p.read_text().splitlines()[1:] if line.split()[3]=='0A')
listeners_before=listeners();assert listeners_before==0
observations=[];normal_hashes={}
for variant in ['original','fixed-control']:
 root=Path('/src')/variant;os.chdir(root)
 source=root/'CMD2.py';assert sha(source)==plan['sources'][variant]
 spec=importlib.util.spec_from_file_location('skf_'+variant.replace('-','_'),source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 assert module.__name__!='__main__';module.app.config.update(TESTING=True);client=module.app.test_client();assert type(client).__module__=='flask.testing'
 for item in plan['requests']:
  reached=[]
  def trace(frame,event,arg):
   caller=frame.f_back
   if event=='call' and frame.f_code.co_filename=='<string>' and caller and caller.f_code.co_filename==str(source):
    constants=list(frame.f_code.co_consts);assert all(type(value) in [str,int,type(None),bool] for value in constants)
    reached.append({'line':caller.f_lineno,'function':caller.f_code.co_name,'kind':'python-eval-frame','compiledNames':list(frame.f_code.co_names),'compiledConstants':constants})
   return trace
  sys.settrace(trace)
  try:response=client.get('/viewer',query_string={} if item['value'] is None else {'lines':item['value']})
  finally:sys.settrace(None)
  body=response.get_data(as_text=True);counts={r['id']:body.count(r['marker']) for r in plan['requests'] if r['kind']=='expression'}
  row={'variant':variant,'role':'upstream-positive-witness' if variant=='original' else 'authored-fix-control','countsTowardMinima':False,'requestId':item['id'],'statusCode':response.status_code,'evalFrames':reached,'responseSha256':hashlib.sha256(response.data).hexdigest(),'markerCounts':counts,'normalLogPresent':'oracle-alpha' in body}
  assert response.status_code==200
  if item['kind']=='normal':
   assert row['normalLogPresent'] and all(value==0 for value in counts.values())
   if variant=='original':normal_hashes[item['id']]=row['responseSha256']
   else:assert normal_hashes[item['id']]==row['responseSha256']
  elif variant=='original':
   assert counts[item['id']]==4 and len(reached)==4
   assert all(e['line']==plan['sinkLine'] and e['function']=='viewer' and e['compiledNames']==['str'] and int(item['marker']) in e['compiledConstants'] for e in reached)
  else:assert all(value==0 for value in counts.values()) and not reached and row['normalLogPresent']
  observations.append(row)
origins={}
for project,module_name in {'Flask':'flask','Werkzeug':'werkzeug','Jinja2':'jinja2','MarkupSafe':'markupsafe','itsdangerous':'itsdangerous','blinker':'blinker','click':'click'}.items():
 imported=importlib.import_module(module_name);origin=Path(imported.__file__).resolve();assert origin.is_relative_to('/deps')
 assert importlib.metadata.version(project)==plan['dependencies'][project];origins[project]={'version':importlib.metadata.version(project),'moduleFile':str(origin),'sha256':sha(origin)}
assert listeners()==0
measured={'nonRootUid':os.geteuid(),'networkInterfaces':['lo'],'sourceAndDependencyMountsReadonly':True,'rootMountReadonly':True,'noCapabilities':True,'noNewPrivileges':True,'seccompEnabled':True,'inputIdentitiesMatched':True,'oneLineControlDiffMatched':True,'tcpListenersBefore':listeners_before,'tcpListenersAfter':listeners(),'writeFailureErrnos':write_failures,'clientClass':type(client).__module__+'.'+type(client).__name__,'testMode':module.app.config['TESTING'],'benignResponseEquivalenceAsserted':True,'markupSafeSpeedupsLoaded':'markupsafe._speedups' in sys.modules}
print(json.dumps({'ok':True,'protocolSha256':sha('/protocol.json'),'probeSha256':measured_probe,'python':sys.version.split()[0],'dependencies':origins,'conditions':{'measured':measured,'declared':{'oldRequirementsReproduced':False,'fixedControlIsAuthored':True,'noImpactBeyondExpressionEvaluationTested':True,'fullApplicationCoverage':False,'noIndependentNegativeSamples':True,'independentSinkCases':1}},'observations':observations}))
