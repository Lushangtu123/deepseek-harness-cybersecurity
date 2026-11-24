"""Invoke only the trusted reviewer and tests; project source remains parse-only data."""
from pathlib import Path
from hashlib import sha256
import errno,json,os,subprocess,sys
assert sys.platform=='linux' and os.geteuid()==65534 and Path('/.dockerenv').is_file()
digest=lambda p:sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads(Path('/protocol.json').read_text());assert digest('/probe.py')==plan['probeSha256']
for name,value in plan['sources'].items():assert digest('/src/'+name)==value
for name,value in plan['reviewFiles'].items():assert digest('/review/'+name)==value
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert status['CapEff'].strip()=='0000000000000000' and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456' and Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert set(os.listdir('/sys/class/net'))=={'lo'}
assert all(not Path(p).exists() for p in ['/home/purge/.ssh','/home/purge/.dsh-improved','/var/run/docker.sock'])
for directory in ['/src','/review','/']:
 try:Path(directory,'NO_WRITE').write_text('x');raise AssertionError('Input writable')
 except OSError as error:assert error.errno==errno.EROFS
test=subprocess.run([sys.executable,'-I','-B','/review/scripts/python_namespace_review.test.py'],capture_output=True,text=True,timeout=8)
assert test.returncode==0,(test.stdout,test.stderr)
reports={}
for phase in ['arity17','combined20','anchors']:
 scan='/review/'+phase+'-scan.json';manifest='/review/'+phase+'-manifest.json'
 assert digest(scan)==plan['scans'][phase]['rawResultSha256']
 p=subprocess.run([sys.executable,'-I','-B','/review/scripts/python_namespace_review.py','/src',manifest,scan],capture_output=True,text=True,timeout=8)
 assert p.returncode==0,p.stderr
 result=json.loads(p.stdout);assert result['state']=='completed' and not result['unmatchedAnchors']
 assert not result['r3Qualified'] and not result['changesFindingDisposition']
 rows=result['observations'];assert len(rows)==plan['expectedObservationsByPhase'][phase]
 exact={(r['path'].removeprefix('/src/'),r['start']['line'],r['start']['col'],r['end']['line'],r['end']['col'],r['start']['offset'],r['end']['offset'])
        for r in json.loads(Path(scan).read_text())['results'] if r['check_id']=='policy.harness.python.dynamic-code-namespace'}
 actual={(r['file'],r['anchor']['line'],r['anchor']['col'],r['anchor']['endLine'],r['anchor']['endCol'],r['anchor']['offset'],r['anchor']['endOffset']) for r in rows};assert exact==actual
 for r in rows:
  assert r['sourceSha256']==plan['sources'][r['file']] and r['disposition']=='unverified'
  assert r['callee']['builtinIdentity']=='unverified' and r['source']['externalControl']=='unverified'
 guards=sorted(r['file'] for r in rows if r['constraint']['state']=='fixed-set-guard-observed');assert guards==(plan['expectedConditionalGuardFiles'] if phase!='anchors' else [])
 assert all(r['constraint']['state']=='unresolved' for r in rows if r['file'] not in guards)
 assert digest(scan)==plan['scans'][phase]['rawResultSha256']
 reports[phase]=result
assert reports['arity17']==reports['combined20']
print(json.dumps({'ok':True,'python':sys.version.split()[0],'probeSha256':digest('/probe.py'),'protocolSha256':digest('/protocol.json'),
                  'sourceIdentityMatched':True,'reviewCodeIdentityMatched':True,'sourcesNotImportedOrExecuted':True,
                  'unitTestExitCode':test.returncode,'unitTestOutput':test.stderr,'reports':reports,
                  'independentCasesAdded':0,'r3Qualified':False}))
