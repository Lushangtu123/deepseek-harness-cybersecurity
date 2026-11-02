#!/usr/bin/env python3
"""Fixed offline Bandit adapter. No project execution, arbitrary commands or targets."""
from pathlib import Path
import argparse,base64,hashlib,json,os,re,subprocess,sys

def validate_payload(value):
 if not isinstance(value,dict) or set(value)!={'snapshotId','seconds','files'} or not isinstance(value['snapshotId'],str) or not re.fullmatch('[a-f0-9]{64}',value['snapshotId']) or type(value['seconds']) is not int or not 1<=value['seconds']<=90:raise ValueError('Invalid handoff')
 if not isinstance(value['files'],list) or not 1<=len(value['files'])<=1000:raise ValueError('Invalid files')
 total=0;seen=set()
 for row in value['files']:
  if not isinstance(row,dict) or set(row)!={'path','sha256','content'}:raise ValueError('Invalid file')
  name=row['path']
  if not isinstance(name,str) or len(name)>400 or not name.endswith('.py') or '\\' in name or any(ord(c)<32 for c in name) or any(not p or p.startswith('.') or p in ['node_modules','vendor','build','dist','__pycache__'] for p in name.split('/')) or name in seen:raise ValueError('Invalid path')
  seen.add(name)
  try:raw=base64.b64decode(row['content'],validate=True);raw.decode('utf-8')
  except (ValueError,TypeError,UnicodeError):raise ValueError('Invalid content') from None
  if len(raw)>1048576 or b'\x00' in raw or hashlib.sha256(raw).hexdigest()!=row['sha256'] or re.search(rb'-----BEGIN [^\r\n]{0,48}PRIVATE KEY|AWS_SECRET_ACCESS_KEY\s*[:=]',raw,re.I):raise ValueError('Invalid bytes')
  total+=len(raw)
 if total>8388608:raise ValueError('Handoff limit')
 return value

REMOTE=r'''
from pathlib import Path
import base64,hashlib,json,os,re,signal,stat,subprocess,sys,time,uuid,resource
mode,identity=sys.argv[1:3]
assert os.getuid()==1000 and 'ID=kali' in Path('/etc/os-release').read_text()
assert re.fullmatch(r'joint-[a-f0-9]{40}',identity) and mode in ['run','status','cancel','worker']
base=Path.home()/'.cache/harness-joint-review';base.mkdir(mode=0o700,parents=True,exist_ok=True)
assert base.resolve()==base and base.stat().st_uid==1000 and base.stat().st_mode&0o077==0
job=base/identity;receipt=job/'receipt.json'
def load(path):
 st=path.lstat()
 assert stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==1000 and st.st_mode&0o077==0 and st.st_size<=12582912
 return json.loads(path.read_text())
def save(path,value):
 temp=path.parent/('.'+uuid.uuid4().hex);fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 os.replace(temp,path)
def alive(process):
 try:
  fields=Path('/proc/'+str(process['pid'])+'/stat').read_text().split()
  return fields[2]!='Z' and fields[21]==process['startTicks'] and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==process['bootId'] and os.getpgid(process['pid'])==process.get('groupPid',process['pid'])
 except (OSError,KeyError):return False
def group_present(process):
 if process['bootId']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():return False
 for path in Path('/proc').iterdir():
  if not path.name.isdigit():continue
  try:
   fields=(path/'stat').read_text().split()
   if path.stat().st_uid==1000 and fields[2]!='Z' and int(fields[4])==process['pid']:return True
  except (OSError,ValueError,IndexError):pass
 return False
def current():
 value=load(receipt)
 if value['state']=='running':
  try:process=load(job/'process.json')
  except FileNotFoundError:process=None
  if process and not alive(process):value.update(state='interrupted',cleanupVerified=False,problem='worker-disappeared')
 if value['state'] in ['interrupted','unconfirmed']:
  try:process=load(job/'process.json')
  except FileNotFoundError:process=None
  if process and not group_present(process):value.update(state='interrupted',cleanupVerified=True,problem='worker-interrupted-original-process-group-gone')
 return value
if mode=='run':
 payload=validate_payload(json.loads(sys.stdin.buffer.read(12582913)))
 try:job.mkdir(mode=0o700)
 except FileExistsError:
  assert job.resolve()==job and job.stat().st_mode&0o077==0
  value=current();assert value['snapshotId']==payload['snapshotId'] and load(job/'payload.json')==payload;print(json.dumps(value));sys.exit(0)
 save(job/'payload.json',payload)
 save(receipt,{'id':identity,'snapshotId':payload['snapshotId'],'state':'running','cleanupVerified':False,'findings':[],'checkedFiles':0})
 source=job/'agent.py';source.write_text(VALIDATE+'\n'+REMOTE);source.chmod(0o600)
 child=subprocess.Popen(['/usr/bin/python3','-I',str(source),'worker',identity],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
 fields=Path('/proc/'+str(child.pid)+'/stat').read_text().split()
 save(job/'process.json',{'pid':child.pid,'startTicks':fields[21],'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
 print(json.dumps(current()));sys.exit(0)
assert job.resolve()==job and job.stat().st_mode&0o077==0
if mode=='status':print(json.dumps(current()));sys.exit(0)
if mode=='cancel':
 value=current()
 if value['state']=='running' or not value.get('cleanupVerified'):
  process=load(job/'process.json')
  def anchor():
   try:child_process=load(job/'child.json')
   except FileNotFoundError:child_process=None
   return alive(process) or bool(child_process and alive(child_process))
  sent=False
  for _ in range(50):
   if not sent and anchor():os.killpg(process['pid'],signal.SIGTERM);sent=True
   value=current()
   if value['state']!='running' and value.get('cleanupVerified'):break
   time.sleep(.1)
  if not value.get('cleanupVerified') and anchor():
   os.killpg(process['pid'],signal.SIGKILL);time.sleep(.1);value=current()
  if not value.get('cleanupVerified'):value.update(state='unconfirmed',cleanupVerified=False,problem='stop-needs-reconciliation')
  save(receipt,value)
 print(json.dumps(value));sys.exit(0)
payload=validate_payload(load(job/'payload.json'));value=load(receipt);child=None;timed_out=False;deadline=time.monotonic()+payload['seconds']
class Cancelled(Exception):pass
def stop(signum,frame):
 global timed_out
 timed_out=signum==signal.SIGALRM
 raise Cancelled()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGALRM,stop)
signal.alarm(payload['seconds']);resource.setrlimit(resource.RLIMIT_FSIZE,(8388608,8388608));resource.setrlimit(resource.RLIMIT_AS,(805306368,805306368))
try:
 for _ in range(100):
  if (job/'process.json').exists():break
  time.sleep(.01)
 else:raise ValueError('process-identity-unavailable')
 python=Path.home()/'.local/share/harness-security/bandit-1.9.4/bin/python'
 if not python.is_file():value.update(state='unavailable',problem='pinned-bandit-not-installed')
 else:
  version=subprocess.run([str(python),'-I','-c',"import importlib.metadata;print(importlib.metadata.version('bandit'))"],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
  if version!='1.9.4':raise ValueError('pinned-bandit-version-mismatch')
  value['version']=version;source=job/'source';source.mkdir(mode=0o700)
  for row in payload['files']:
   path=source/row['path'];path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.write_bytes(base64.b64decode(row['content']));path.chmod(0o400)
  (job/'fixed.yaml').write_text('{}\n');(job/'fixed.ini').write_text('')
  output=job/'result.json'
  launcher=job/'launch.py';launcher.write_text(r"""
from pathlib import Path
import json,math,os,signal,sys,time,uuid
job=Path(sys.argv[1]);python=sys.argv[2];deadline=float(sys.argv[3])
fields=Path('/proc/self/stat').read_text().split()
record={'pid':os.getpid(),'groupPid':os.getpgrp(),'startTicks':fields[21],'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
temp=job/('.child-'+uuid.uuid4().hex);fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
os.replace(temp,job/'child.json')
# The kernel alarm survives exec, bounding the analyzer even if its supervisor dies.
remaining=math.ceil(deadline-time.monotonic())
if remaining<=0:raise SystemExit(124)
signal.alarm(remaining)
os.execve(python,[python,'-I','-m','bandit','--ignore-nosec','-q','-r',str(job/'source'),'-f','json','-o',str(job/'result.json'),'-c',str(job/'fixed.yaml'),'--ini',str(job/'fixed.ini')],{'PATH':'/usr/bin:/bin','HOME':str(job),'LANG':'C.UTF-8','PYTHONNOUSERSITE':'1'})
""")
  launcher.chmod(0o600)
  child=subprocess.Popen(['/usr/bin/python3','-I',str(launcher),str(job),str(python),str(deadline)],cwd=job,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
  code=child.wait(timeout=payload['seconds']);assert code in [0,1] and output.stat().st_size<=8388608
  report=json.loads(output.read_text());assert isinstance(report['results'],list) and isinstance(report['errors'],list)
  allowed={row['path'] for row in payload['files']};findings=[]
  for row in report['results'][:2000]:
   name=str(Path(row['filename']).relative_to(source));assert name in allowed
   findings.append({'path':name,'line':row['line_number'],'rule':row['test_id'],'title':str(row['issue_text'])[:400],'severity':str(row['issue_severity']).lower()})
  errors=[]
  for error in report['errors'][:20]:
   try:name=str(Path(error['filename']).relative_to(source))
   except (ValueError,KeyError):name=''
   errors.append({'path':name if name in allowed else '', 'code':'bandit-file-incomplete'})
  value.update(state='partial' if report['errors'] or len(report['results'])>2000 else 'completed',findings=findings,diagnostics=errors,diagnosticsTotal=len(report['errors']),diagnosticsTruncated=len(report['errors'])>20,checkedFiles=max(0,len(allowed)-len(report['errors'])),problem='parse-or-output-gap' if report['errors'] or len(report['results'])>2000 else None)
except Cancelled:value.update(state='timed-out' if timed_out else 'cancelled',problem='deadline' if timed_out else 'cancelled')
except subprocess.TimeoutExpired:value.update(state='timed-out',problem='deadline')
except BaseException:value.update(state='failed',problem='fixed-offline-check-failed')
finally:
 signal.alarm(0);signal.signal(signal.SIGTERM,signal.SIG_IGN)
 cleanup=True
 if child and child.poll() is None:
  child.kill()
  try:child.wait(timeout=3)
  except subprocess.TimeoutExpired:cleanup=False
 value['cleanupVerified']=cleanup;save(receipt,value)
'''

def remote_argv(mode,identity):
 if mode not in ['run','status','cancel'] or not re.fullmatch('joint-[a-f0-9]{40}',identity):raise ValueError('Invalid action')
 import inspect
 validate='from pathlib import Path\nimport base64,hashlib,json,os,re,subprocess,sys\n'+inspect.getsource(validate_payload)
 source='VALIDATE='+repr(validate)+'\nREMOTE='+repr(REMOTE)+'\n'+validate+'\n'+REMOTE
 return ['/home/purge/.local/bin/kali-vm','exec','--','python3','-I','-c',source,mode,identity]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['run','status','cancel']);parser.add_argument('id');args=parser.parse_args()
 payload=None
 if args.mode=='run':payload=json.dumps(validate_payload(json.loads(sys.stdin.buffer.read(12582913)))).encode()
 try:
  result=subprocess.run(remote_argv(args.mode,args.id),input=payload,capture_output=True,timeout=12)
  if result.returncode or len(result.stdout)>2097152:raise ValueError('Remote receipt unavailable')
  value=json.loads(result.stdout);assert value['id']==args.id
  print(json.dumps(value));return 0
 except (OSError,ValueError,AssertionError,subprocess.SubprocessError):
  print(json.dumps({'id':args.id,'state':'unconfirmed','cleanupVerified':False,'problem':'query-original-id-before-any-new-run'}));return 1
if __name__=='__main__':raise SystemExit(main())
