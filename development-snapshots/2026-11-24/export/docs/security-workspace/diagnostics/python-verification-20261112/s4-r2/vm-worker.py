from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import base64,importlib.util,json,os,subprocess,traceback,time,sqlite3
root=Path(__file__).resolve().parent;home=Path('/home/purge');daily=home/'.dsh-improved';installed=home/'tools/dsh-purge-personal-1.1.77-personal.1';runtime=home/'tools/harness-improved-runtime/node_modules';node=str(home/'.local/node/bin/node');IMAGE='sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7'
def write(n,v):(root/n).write_text(json.dumps(v,indent=2)+'\n')
def module(n):
 spec=importlib.util.spec_from_file_location(n.replace('/','_'),root/n);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def cmd(a,codes=(0,),timeout=90):
 p=subprocess.run(a,cwd=root,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
 if p.returncode not in codes:raise ValueError(f'{a[0]} failed {p.returncode}: '+p.stderr[-1500:].decode(errors='replace'))
 return p
try:
 payload=json.loads((root/'input.json').read_bytes())
 for n,raw in payload['files'].items():
  p=root/n;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);data=base64.b64decode(raw,validate=True);assert sha256(data).hexdigest()==payload['checks'][n];p.write_bytes(data)
 protected={};exec(compile((root/'identity-code.py').read_text(),'identity-code.py','exec'),globals(),protected);identify=protected['identity'];globals()['digest']=protected['digest'];before=identify()
 api=module('scripts/reviewer_snapshot.py');vs=module('scripts/verifier_snapshot.py');static=api.freeze(root/'modules',root/'static',IMAGE);staticpin=api.digest(static)
 container_policies=[]
 class InspectEngine(api.DockerEngine):
  def invoke(self,args,seconds,phase,cancellable=True):
   if phase=='start' and self.job.get('operation')=='verify-execution':
    details=json.loads(super().invoke(['container','inspect',args[-1]],6,'acceptance-policy',False)['stdout'])[0];host=details['HostConfig'];config=details['Config'];mounts=details['Mounts']
    assert config['User']=='1000:1000' and host['NetworkMode']=='none' and host['ReadonlyRootfs'] is True
    assert host['Memory']==536870912 and host['MemorySwap']==536870912 and host['NanoCpus']==1000000000 and host['PidsLimit']==64
    assert host['CapDrop']==['ALL'] and not host['CapAdd'] and not host['Privileged'] and 'no-new-privileges' in host['SecurityOpt']
    assert len(mounts)==1 and mounts[0]['Destination']=='/review' and mounts[0]['RW'] is False
    stage=Path(mounts[0]['Source']);assert stage==self.root/'stage' and stage.stat().st_mode&0o077==0
    source_stage=stage/'sources';expected=json.loads((stage/'manifest.json').read_bytes())['files']
    staged={str(p.relative_to(source_stage)):sha256(p.read_bytes()).hexdigest() for p in source_stage.rglob('*') if p.is_file()}
    assert staged==expected and all(not p.is_symlink() for p in source_stage.rglob('*'))
    assert 'size=32m' in host['Tmpfs']['/tmp'] and 'seccomp=unconfined' not in host['SecurityOpt']
    container_policies.append({'user':config['User'],'stagedSourceClosureVerified':True,'stagedSources':staged,'hostConfig':{k:host[k] for k in ['NetworkMode','ReadonlyRootfs','Memory','MemorySwap','NanoCpus','PidsLimit','CapDrop','CapAdd','Privileged','SecurityOpt','Tmpfs']},'mounts':[{'destination':m['Destination'],'rw':m['RW'],'type':m['Type']} for m in mounts]})
   return super().invoke(args,seconds,phase,cancellable)
 source_files={str(p.relative_to(root/'sources')):sha256(p.read_bytes()).hexdigest() for p in (root/'sources').rglob('*.py')};write('locations-manifest.json',{'files':source_files})
 locations=api.locations(root/'static',staticpin,root/'sources',root/'locations-manifest.json',attempts_root=root/'attempts');write('locations.json',locations)
 contracts=json.loads((root/'contracts.json').read_bytes());verifier=vs.freeze(root/'static',staticpin,root/'vendor',json.loads((root/'dependency-lock.json').read_bytes()),list(contracts.values()),root/'verifier');write('verifier-snapshot.json',verifier)
 # All sources in this profile must be the audited original bytes.
 assert all(h in verifier['sourceProfiles'] for h in source_files.values())
 docker=['/usr/bin/sudo','-n','/usr/bin/docker']
 for arm in ['baseline','candidate']:
  output=cmd([*docker,'run','--rm','--pull','never','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','768m','--memory-swap','768m','--cpus','1','--pids-limit','64','--log-driver','none','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777','--env','HOME=/tmp','--mount',f'type=bind,src={root/"sources"},dst=/src,readonly','--mount',f'type=bind,src={root/(arm+"-rules.json")},dst=/policy/rules.json,readonly','--entrypoint','semgrep',IMAGE,'scan','--config','/policy/rules.json','--json','--metrics=off','--disable-version-check','--jobs','1','/src'])
  (root/(arm+'-scan.json')).write_bytes(output.stdout);scan=json.loads(output.stdout);assert scan['errors']==[]
 cmd([node,'score.mjs','freeze'])
 binding=json.loads((root/'binding.json').read_bytes());scanpath=root/'candidate-scan.json';write('review-manifest.json',{'files':source_files,'scanSha256':sha256(scanpath.read_bytes()).hexdigest(),'locationBinding':locations['locationBinding'],'discoverImports':True})
 write('run-start.json',{'startedAt':datetime.now(timezone.utc).isoformat()});time.sleep(.01)
 static_result=api.execute(root/'static',staticpin,root/'sources',root/'review-manifest.json',scanpath,binding['datasetSha256'],binding['freezeSha256'],attempts_root=root/'attempts');write('static-result.json',static_result)
 results=[]
 plan=json.loads((root/'verification-plan.json').read_bytes())
 assert len(plan['requests'])<=8
 for i,request in enumerate(plan['requests']):
  value={k:request[k] for k in ['contract','point','challenge']};value['version']=1;path=root/('request-'+str(i)+'.json');write(path.name,value)
  if i==0:(root/'sources/unlisted.py').write_text('raise RuntimeError(\"unlisted source must stay outside stage\")\n')
  result=api.verify_execution(root/'verifier',api.digest(verifier),root/'sources',root/'review-manifest.json',scanpath,path,binding['datasetSha256'],binding['freezeSha256'],attempts_root=root/'attempts',_engine_factory=InspectEngine);write('verification-'+str(i)+'.json',result)
  assert api.status(Path(result['attemptDirectory']))['result']==result
  assert api.recover(Path(result['attemptDirectory']))['result']==result
  assert result['cleanup']['confirmed'] and result['verificationExecution']['cleanupVerified'];results.append(result)
 (root/'sources/unlisted.py').unlink();write('verifications.json',results);cmd([node,'score.mjs','score'])
 # Unsupported sources are diagnostic boundary tests, never new holdout evaluation.
 boundaries={
  'fixed-marker': "def route(value):\n    return eval(\"'harness-control'\")\n",
  'quoted-echo': "def route(value):\n    return eval(repr(value))\n",
  'same-name': "def eval(value):\n    return value\ndef route(value):\n    return eval(value)\n",
  'rebound': "eval = str\ndef route(value):\n    return eval(value)\n",
  'after-guard-overwrite': "def route(value):\n    if value not in ('1',):\n        return 'rejected'\n    value = input()\n    return eval(value)\n",
  'dangerous-whitelist': "def route(value):\n    if value not in (\"str(1)\",):\n        return 'rejected'\n    return eval(value)\n",
  'same-line': "def route(value):\n    return eval(value), eval(value)\n",
  'nested': "def route(value):\n    return eval(eval(value))\n",
  'loop-not-executed': "def route(value):\n    while True: pass\n    return eval(value)\n",
  'fd-output': "import os\ndef route(value):\n    os.write(1, b'{}')\n    return eval(value)\n",
  'cross-file': "from helper import forward\ndef route(value):\n    return eval(forward(value))\n"
 }
 boundary_results=[]
 for name,source in boundaries.items():
  project=root/'boundary-sources'/name;project.mkdir(parents=True);(project/'literal-set.py').write_text(source)
  if name=='cross-file':(project/'helper.py').write_text('def forward(value):\n    return value\n')
  files={str(p.relative_to(project)):sha256(p.read_bytes()).hexdigest() for p in project.rglob('*.py')};manifest=root/(name+'-manifest.json');write(manifest.name,{'files':files})
  loc=api.locations(root/'static',staticpin,project,manifest,attempts_root=root/'attempts')
  point=loc['locationBinding']['inventory']['files']['literal-set.py']['points'][0]
  scan=root/(name+'-scan.json');write(scan.name,{'results':[],'errors':[]});write(manifest.name,{'files':files,'scanSha256':sha256(scan.read_bytes()).hexdigest(),'locationBinding':loc['locationBinding']})
  path=root/(name+'-request.json');write(path.name,{'version':1,'contract':contracts['literal-set.py'],'point':point,'challenge':sha256(('diagnostic-'+name).encode()).hexdigest()})
  value=api.verify_execution(root/'verifier',api.digest(verifier),project,manifest,scan,path,'d'*64,'e'*64,attempts_root=root/'attempts',_engine_factory=InspectEngine)
  assert value['report']['decision']=='unknown' and len(value['report']['runs'])==4
  assert all(r['trace'].get('reason')=='source-profile-not-reviewed' for r in value['report']['runs'])
  assert api.recover(Path(value['attemptDirectory']))['result']==value and value['cleanup']['confirmed']
  boundary_results.append({'name':name,'sourceFiles':files,'expected':'unknown-before-project-execution','result':value,'locations':loc})
 write('boundary-results.json',boundary_results);write('container-policies.json',container_policies)
 assert len(container_policies)==4+len(boundaries)

 after=identify();assert before==after
 names=['locations.json','verifier-snapshot.json','diagnostic-dataset.json','diagnostic-freeze.json','verification-plan.json','diagnostic-run.json','vm-quality.json','case-evidence.json','binding.json','static-result.json','verifications.json','baseline-scan.json','candidate-scan.json','policy.json','ledger.json','review-manifest.json','snapshot-identity.json','boundary-results.json','container-policies.json']
 evidence={n:(root/n).read_bytes().decode() for n in names};result={'state':'completed','sourcesVerified':payload['checks'],'dailyProgramFilesMatched':len(before['program']),'dailyDatabasesMatched':len(before['databases']),'dailyProtection':{k:{'before':sha256(json.dumps(v,sort_keys=True).encode()).hexdigest(),'after':sha256(json.dumps(after[k],sort_keys=True).encode()).hexdigest()} for k,v in before.items()},'artifacts':evidence,'artifactSha256':{n:sha256(v.encode()).hexdigest() for n,v in evidence.items()}}
 write('result.json',result)
except Exception:write('result.json',{'state':'failed','trace':traceback.format_exc()[-6000:]});raise
