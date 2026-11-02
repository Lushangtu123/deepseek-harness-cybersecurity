#!/usr/bin/env python3
"""Offline, explicit Semgrep candidate admission; never downloads an image."""
from pathlib import Path
import fcntl,hashlib,importlib.util,json,os,re,stat,subprocess,sys,tempfile,uuid
from datetime import datetime,timezone
HOME=Path('/home/purge');ROOT=HOME/'tools/security-workbench'
IMAGE=re.compile(r'sha256:[a-f0-9]{64}\Z');VERSION=re.compile(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z');HASH=re.compile(r'[a-f0-9]{64}\Z')
class UpdateError(Exception):pass

def ordinary(path,limit=131072):
 path=Path(path)
 if path.resolve()!=path:raise UpdateError('Unsafe scanner resource path')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or not 0<info.st_size<=limit:raise UpdateError('Invalid scanner resource')
  with os.fdopen(fd,'rb',closefd=False) as source:raw=source.read(limit+1)
  if len(raw)>limit:raise UpdateError('Scanner resource exceeds bound')
  return raw
 finally:os.close(fd)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def atomic(path,raw,mode=0o600):
 if path.parent.resolve()!=path.parent or path.is_symlink():raise UpdateError('Unsafe scanner target')
 fd,name=tempfile.mkstemp(dir=path.parent,prefix='.scanner-')
 try:
  with os.fdopen(fd,'wb') as out:os.fchmod(out.fileno(),mode);out.write(raw);out.flush();os.fsync(out.fileno())
  os.replace(name,path)
 finally:Path(name).unlink(missing_ok=True)
def write(path,value):atomic(path,(json.dumps(value,indent=2)+'\n').encode())
def stamp():return datetime.now(timezone.utc).isoformat()
def validate_request(request):
 if not isinstance(request,dict) or set(request)!={'imageId','version','expectedManifestSha256','confirm'} or not IMAGE.fullmatch(request.get('imageId','')) or not VERSION.fullmatch(request.get('version','')) or not HASH.fullmatch(request.get('expectedManifestSha256','')) or request['confirm'] is not True:raise UpdateError('Exact candidate, expected manifest and explicit confirmation required')
def manifest(raw):
 value=json.loads(raw)
 if value.get('schemaVersion')!=1 or not isinstance(value.get('tools'),list) or len(value['tools'])!=3:raise UpdateError('Invalid scanner manifest')
 for tool in ['semgrep','trivy','zap']:
  rows=[row for row in value['tools'] if isinstance(row,dict) and row.get('tool')==tool]
  if len(rows)!=1 or not IMAGE.fullmatch(rows[0].get('imageId','')) or rows[0].get('imageRef')!='personal-security/'+tool+'@'+rows[0]['imageId'] or not VERSION.fullmatch(rows[0].get('version','')):raise UpdateError('Invalid scanner pin')
 return value

def apply_candidate(root,request,*,probe,check_idle,stop,start,validate):
 root=Path(root);validate_request(request)
 if root.resolve()!=root or not root.is_dir():raise UpdateError('Ordinary scanner root required')
 fd=os.open(root/'.db-update.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise UpdateError('Scanner or database maintenance already running')
  if os.path.lexists(root/'maintenance.json'):raise UpdateError('Earlier maintenance needs recovery')
  before=ordinary(root/'images.json');value=manifest(before)
  if sha(before)!=request['expectedManifestSha256'] or check_idle() is not True:raise UpdateError('Scanner manifest changed or task active')
  result=probe(request['imageId'],request['version'])
  if not isinstance(result,dict) or result.get('parserReady') is not True or result.get('controlsPassed') is not True or result.get('imageId')!=request['imageId'] or result.get('version')!=request['version']:raise UpdateError('Candidate parser admission failed; installed pin unchanged')
  if sha(ordinary(root/'images.json'))!=request['expectedManifestSha256'] or check_idle() is not True:raise UpdateError('Scanner state changed during candidate check')
  desired=json.loads(before);row=next(row for row in desired['tools'] if row['tool']=='semgrep')
  row.update(imageId=request['imageId'],imageRef='personal-security/semgrep@'+request['imageId'],version=request['version'])
  if row==next(row for row in value['tools'] if row['tool']=='semgrep'):return {'changed':False,'checkedAt':stamp(),'imageId':row['imageId'],'version':row['version']}
  after=(json.dumps(desired,indent=2)+'\n').encode();backups=root/'scanner-backups';backups.mkdir(mode=0o700,exist_ok=True)
  if backups.resolve()!=backups:raise UpdateError('Unsafe backup path')
  backup=backups/uuid.uuid4().hex;backup.mkdir(mode=0o700);atomic(backup/'before-manifest.json',before)
  journal={'schemaVersion':1,'kind':'scanner-image','phase':'prepared','beforeManifestSha256':sha(before),'afterManifestSha256':sha(after),'manifestMode':stat.S_IMODE((root/'images.json').stat().st_mode)};write(backup/'journal.json',journal)
  write(root/'maintenance.json',{'state':'updating','kind':'scanner-image','backup':backup.name,'startedAt':stamp()});attempted=False;starting=False
  try:
   attempted=True;stop()
   if check_idle() is not True or sha(ordinary(root/'images.json'))!=request['expectedManifestSha256']:raise UpdateError('Scanner state changed before commit')
   atomic(root/'images.json',after,journal['manifestMode']);journal['phase']='installed';write(backup/'journal.json',journal)
   if validate() is not True:raise UpdateError('Candidate runtime validation failed')
   starting=True;start();journal['phase']='committed';write(backup/'journal.json',journal)
   result={'changed':True,'checkedAt':stamp(),'backup':str(backup),'imageId':request['imageId'],'version':request['version']};write(root/'last-scanner-update.json',{'state':'updated',**result});(root/'maintenance.json').unlink();return result
  except BaseException as error:
   try:
    if starting:stop()
    rollback(root,backup,journal)
    if attempted:start()
    write(root/'last-scanner-update.json',{'state':'rolled-back','checkedAt':stamp(),'backup':str(backup)});(root/'maintenance.json').unlink()
   except BaseException as recovery:raise UpdateError('Scanner recovery needs inspection') from recovery
   raise UpdateError('Candidate failed; original scanner restored') from error
 finally:os.close(fd)

def rollback(root,backup,journal):
 before=ordinary(backup/'before-manifest.json')
 if sha(before)!=journal['beforeManifestSha256'] or sha(ordinary(root/'images.json')) not in {journal['beforeManifestSha256'],journal['afterManifestSha256']}:raise UpdateError('Scanner manifest changed outside this transaction')
 manifest(before);atomic(root/'images.json',before,journal['manifestMode']);journal['phase']='rolled-back';write(backup/'journal.json',journal)

def recover_candidate(root,*,check_idle,stop,start):
 root=Path(root)
 if root.resolve()!=root:raise UpdateError('Unsafe scanner root')
 fd=os.open(root/'.db-update.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise UpdateError('Maintenance already running')
  marker=json.loads(ordinary(root/'maintenance.json',16384));name=marker.get('backup','')
  if marker.get('kind')!='scanner-image' or not re.fullmatch('[a-f0-9]{32}',name):raise UpdateError('Not a scanner recovery marker')
  backup=root/'scanner-backups'/name;journal=json.loads(ordinary(backup/'journal.json',16384))
  if journal.get('schemaVersion')!=1 or journal.get('kind')!='scanner-image' or any(not isinstance(journal.get(k),str) or not HASH.fullmatch(journal[k]) for k in ['beforeManifestSha256','afterManifestSha256']) or type(journal.get('manifestMode')) is not int or not 0<=journal['manifestMode']<=0o777:raise UpdateError('Invalid scanner journal')
  if check_idle() is not True:raise UpdateError('Scanner active')
  stop()
  try:
   if check_idle() is not True:raise UpdateError('Scanner became active')
   rollback(root,backup,journal);start()
  except BaseException:raise UpdateError('Scanner recovery not confirmed; marker retained')
  (root/'maintenance.json').unlink();result={'recovered':True,'backup':str(backup),'checkedAt':stamp()};write(root/'last-scanner-update.json',{'state':'rolled-back',**result});return result
 finally:os.close(fd)

def candidate_probe(image,expected_version):
 if not isinstance(image,str) or not IMAGE.fullmatch(image) or not isinstance(expected_version,str) or not VERSION.fullmatch(expected_version):raise UpdateError('Immutable local candidate identity required')
 spec=importlib.util.spec_from_file_location('harness_parser_admission',Path(__file__).with_name('security-parser-check.py'));parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
 report=parser.check(image)
 name='harness-version-'+uuid.uuid4().hex[:12]
 try:
  command='semgrep --version > /tmp/version 2>/dev/null; code=$?; head -c 1025 /tmp/version; exit "$code"'
  r=subprocess.run(['sudo','-n','/usr/bin/docker','run','--rm','--pull','never','--name',name,'--label','personal.harness.parser.probe=true','--log-driver','none','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','256m','--cpus','1','--user','1000:1000','--tmpfs','/tmp:rw,nosuid,nodev,size=16777216','--env','HOME=/tmp','--env','SEMGREP_ENABLE_VERSION_CHECK=0','--entrypoint','/bin/sh',image,'-c',command],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15)
  if r.returncode or len(r.stdout)>1024 or r.stdout.strip()!=expected_version:raise UpdateError('Candidate executable version mismatch')
 finally:
  subprocess.run(['sudo','-n','/usr/bin/docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
  left=subprocess.run(['sudo','-n','/usr/bin/docker','ps','-aq','--filter','name=^/'+name+'$'],capture_output=True,text=True,timeout=8)
  if left.returncode or left.stdout.strip():raise UpdateError('Candidate version container cleanup not confirmed')
 report['version']=expected_version;return report

def dedicated():
 if sys.platform!='linux' or Path.home()!=HOME or os.getuid()!=1000 or (HOME/'.config/harness-vm-mode').read_text().strip()!='improved':raise UpdateError('Dedicated improved VM required')
def idle():
 import sqlite3
 env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'}
 r=subprocess.run(['sudo','-n','/usr/bin/docker','ps','--filter','label=personal.harness.security=true','--format','{{.Names}}'],capture_output=True,text=True,check=True,timeout=8)
 if r.stdout.strip():return False
 for path in (HOME/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
  if path.resolve()!=path:raise UpdateError('Unsafe engagement database')
  db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=2)
  try:
   if db.execute("SELECT 1 FROM sqlite_master WHERE name='security_run'").fetchone() and db.execute("SELECT 1 FROM security_run WHERE state='running' LIMIT 1").fetchone():return False
  finally:db.close()
 return True
def service(action):
 subprocess.run(['systemctl','--user',action,'dsh-original','harness-security.socket','harness-security.service'],env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},capture_output=True,check=True,timeout=45)
def validate_runtime():
 r=subprocess.run([str(HOME/'.local/node/bin/node'),str(Path(__file__).with_name('security-runtime-preflight.mjs')),'--validating-update'],capture_output=True,text=True,timeout=20)
 return r.returncode==0 and json.loads(r.stdout).get('ok') is True

def main(argv=None):
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image-id');parser.add_argument('--version');parser.add_argument('--expected-manifest-sha256');mode=parser.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--recover-last',action='store_true');parser.add_argument('--confirm',action='store_true');args=parser.parse_args(argv)
 try:
  dedicated()
  if args.recover_last:
   if not args.confirm or any([args.image_id,args.version,args.expected_manifest_sha256]):raise UpdateError('Explicit recovery confirmation required')
   result=recover_candidate(ROOT,check_idle=idle,stop=lambda:service('stop'),start=lambda:service('start'))
  elif args.apply:
   result=apply_candidate(ROOT,{'imageId':args.image_id,'version':args.version,'expectedManifestSha256':args.expected_manifest_sha256,'confirm':args.confirm},probe=candidate_probe,check_idle=idle,stop=lambda:service('stop'),start=lambda:service('start'),validate=validate_runtime)
  else:
   if args.confirm or args.expected_manifest_sha256:raise UpdateError('Unexpected check arguments')
   raw=ordinary(ROOT/'images.json');manifest(raw)
   if os.path.lexists(ROOT/'maintenance.json'):raise UpdateError('Maintenance pending recovery')
   report=candidate_probe(args.image_id,args.version)
   if ordinary(ROOT/'images.json')!=raw:raise UpdateError('Manifest changed during check')
   result={'checkedAt':stamp(),'manifestSha256':sha(raw),'changed':False,'candidate':{'imageId':args.image_id,'version':args.version},'admitted':report['parserReady'] is True and report['controlsPassed'] is True,'parser':report,'scope':'Eight synthetic parser/rule controls, not complete project coverage'}
   print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['admitted'] else 2
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except KeyboardInterrupt:print(json.dumps({'ok':False,'error':'操作已中断；请先核对维护记录，不自动重试。'},ensure_ascii=False));return 130
 except Exception:print(json.dumps({'ok':False,'error':'候选未通过、清单已变化或维护未确认；不会自动下载、切换或重试。请核对扫描器维护状态。'},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
