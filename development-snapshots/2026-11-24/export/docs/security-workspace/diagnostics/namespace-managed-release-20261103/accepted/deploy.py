from pathlib import Path
import sys,os
if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE"):raise RuntimeError("Run release with Python optimization disabled")
from hashlib import sha256
import base64,gzip,importlib.util,json,time
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm'
expected=json.loads((w/'archive.json').read_text());old=json.loads((w/'baseline.json').read_text())['program'];new=json.loads((w/'candidate-program.json').read_text());baseline=json.loads((w/'baseline.json').read_text())
assert new==json.loads((repo/'work/harness-purge-improved/package-files.json').read_text())
assert sha256((w/'harness-vm-candidate.tar.gz').read_bytes()).hexdigest()==expected['archiveSha256']
archive=base64.b64encode((w/'harness-vm-candidate.tar.gz').read_bytes()).decode()
source=f'ARCHIVE={archive!r}\nEXPECTED={expected!r}\nOLD={old!r}\nNEW={new!r}\nBASELINE={baseline!r}\n'+(w/'deploy-remote.py').read_text()
# This supervisor belongs to the VM user manager, independently of any SSH connection.
bootstrap="""
from pathlib import Path
import json,os
operation=Path('/home/purge/.cache/harness-namespace-managed-release-retry1-20261103.operation')
def atomic_json(path,value):
 p=path.with_name(path.name+'.tmp')
 with p.open('w') as f:
  p.chmod(0o600);json.dump(value,f);f.flush();os.fsync(f.fileno())
 p.replace(path);fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def outcome(name,value):atomic_json(operation/(name+'.json'),value)
try:
 exec(compile(SOURCE,'namespace-release','exec'),globals())
 outcome('result',result)
except BaseException as error:
 p=Path('/home/purge/.cache/harness-namespace-managed-release-retry1-20261103/state.json')
 outcome('failure',{'errorType':type(error).__name__,'state':json.loads(p.read_text()) if p.is_file() else None})
 raise
"""
payload=base64.b64encode(gzip.compress(('SOURCE='+repr(source)+'\n'+bootstrap).encode())).decode()
launch='PAYLOAD='+repr(payload)+'\n'+r'''
from pathlib import Path
import base64,gzip,json,os,subprocess
linger=subprocess.check_output(['loginctl','show-user','purge','-p','Linger','--value'],text=True,timeout=5).strip();assert linger=='yes'
op=Path('/home/purge/.cache/harness-namespace-managed-release-retry1-20261103.operation');assert not op.exists();op.mkdir(mode=0o700)
p=op/'run.py';p.write_bytes(gzip.decompress(base64.b64decode(PAYLOAD)));p.chmod(0o600)
env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'}
r=subprocess.run(['systemd-run','--user','--collect','--unit=harness-namespace-managed-release-retry1-20261103','--property=Type=exec','--property=RuntimeMaxSec=600','--property=TimeoutStopSec=420','--property=KillMode=mixed','--','/usr/bin/python3','-I','-B',str(p)],env=env,capture_output=True,text=True,timeout=20)
assert r.returncode==0,r.stderr
print(json.dumps({'supervisor':'systemd-user-transient-service','operation':str(op),'detachedFromSSH':True,'linger':linger,'isolatedPython':True}))
'''
query=r'''
from pathlib import Path
import json,os,subprocess
op=Path('/home/purge/.cache/harness-namespace-managed-release-retry1-20261103.operation');backup=Path('/home/purge/.cache/harness-namespace-managed-release-retry1-20261103')
unit=subprocess.run(['systemctl','--user','show','harness-namespace-managed-release-retry1-20261103','-p','ActiveState','-p','LoadState','-p','Result','-p','ExecMainStatus'],env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},capture_output=True,text=True,timeout=5)
u=dict(line.split('=',1) for line in unit.stdout.splitlines() if '=' in line)
print(json.dumps({n:json.loads(p.read_text()) if (p:=op/(n+'.json')).is_file() else None for n in ['result','failure']}|{'unit':u,'state':json.loads(p.read_text()) if (p:=backup/'state.json').is_file() else None}))
'''
spec=importlib.util.spec_from_file_location('manager',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
try:
 with m.vm_operation('switch'):
  receipt=json.loads(m.ssh('python3 -B -',input=launch,timeout=45,phase='program-update').stdout);(w/'deploy-launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
  until=time.monotonic()+1080
  while True:
   try:observation=json.loads(m.ssh('python3 -B -',input=query,timeout=15,phase='program-update').stdout)
   except (m.SSHFailure,ValueError):
    if time.monotonic()>=until:raise RuntimeError('VM outcome unknown; original operation needs inspection')
    time.sleep(1);continue
   (w/'deploy-observation.json').write_text(json.dumps(observation,indent=2)+'\n')
   if observation['failure']:
    phase=(observation['failure'].get('state') or {}).get('phase')
    raise RuntimeError('Candidate commit recorded but result incomplete; inspect original operation' if phase=='candidate-service-active' else 'VM release failed; inspect recorded rollback state')
   if observation['result']:value=observation['result'];break
   if observation['unit'].get('ActiveState') in ('inactive','failed') or observation['unit'].get('LoadState')=='not-found':raise RuntimeError('Supervisor ended without outcome; inspect original on-disk state, never relaunch')
   if time.monotonic()>=until:raise RuntimeError('VM release outcome unknown; inspect original operation, do not relaunch')
   time.sleep(1)
 host=json.loads((w/'host-baseline.json').read_text());assert all(sha256(Path(n).read_bytes()).hexdigest()==h for n,h in host.items());value['hostManagerAndVMConfigUnchanged']=True
except BaseException as e:
 data={'errorType':type(e).__name__,'vmOutcome':'committed' if 'value' in locals() else 'inspect deploy-observation and VM state','inspectOperation':'/home/purge/.cache/harness-namespace-managed-release-retry1-20261103.operation','relaunchAllowed':False}
 (w/'deploy-controller-failure.json').write_text(json.dumps(data,indent=2)+'\n');raise
(w/'deploy.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
