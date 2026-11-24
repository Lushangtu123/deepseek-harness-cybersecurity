"""Manual Mac-side official Trivy database download and dedicated-VM import."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,gzip,signal,hashlib,http.cookiejar,importlib.util,json,os,re,shlex,subprocess,sys,tarfile,tempfile,time,urllib.request,urllib.parse,uuid
from security_db_transaction import validate_metadata,timestamp

MAX_COMPRESSED=768*1024**2
MAX_DATABASE=2*1024**3

# Bind publisher evidence to both the OCI database manifest and its archive layer.
# The Trivy executable image signature does not authorize a database candidate.
VERIFIED_DATABASE_PUBLISHER_PINS=frozenset()


class UpdateNotice(Exception):pass

def unpack_verified(archive,target,expected_sha,now=None):
 archive=Path(archive);target=Path(target)
 if archive.is_symlink() or archive.stat().st_size>MAX_COMPRESSED:raise ValueError('Invalid archive')
 with archive.open('rb') as stream:
  if hashlib.file_digest(stream,'sha256').hexdigest()!=expected_sha:raise ValueError('Database archive digest mismatch')
 target.mkdir(mode=0o700);seen=set();total=0
 # Parse ordinary headers directly: tarfile's iterator consumes PAX/GNU extension
 # payloads before yielding a member, which would bypass our per-entry limits.
 with gzip.open(archive,'rb') as source:
  while True:
   header=source.read(512)
   if len(header)!=512:raise ValueError('Truncated database archive header')
   if header==bytes(512):
    tail=source.read(32769)
    if len(tail)>32768 or any(tail):raise ValueError('Invalid database archive trailer')
    break
   member=tarfile.TarInfo.frombuf(header,'utf-8','strict')
   if member.name not in {'trivy.db','metadata.json'} or member.name in seen or not member.isfile() or member.size<1 or member.size>(MAX_DATABASE if member.name=='trivy.db' else 16384):raise ValueError('Unsafe database archive entry')
   seen.add(member.name);remaining=member.size
   with (target/member.name).open('xb') as outgoing:
    while remaining:
     block=source.read(min(512*1024,remaining))
     if not block:raise ValueError('Truncated database entry')
     remaining-=len(block);total+=len(block)
     if total>MAX_DATABASE+16384:raise ValueError('Database archive exceeds limits')
     outgoing.write(block)
   padding=source.read((-member.size)%512)
   if len(padding)!=(-member.size)%512 or any(padding):raise ValueError('Invalid database archive padding')
   (target/member.name).chmod(0o444)
 if seen!={'trivy.db','metadata.json'}:raise ValueError('Database archive missing required files')
 metadata=validate_metadata(json.loads((target/'metadata.json').read_text()),now);db=target/'trivy.db'
 if db.stat().st_size<4096:raise ValueError('Database is too small')
 with db.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
 return{'metadata':metadata,'fileSha256':sha,'fileBytes':db.stat().st_size,'archiveSha256':expected_sha}

class PublicRegistryRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  parsed=urllib.parse.urlsplit(newurl)
  if parsed.scheme!='https' or parsed.hostname not in {'ghcr.io','pkg-containers.githubusercontent.com'} or parsed.port not in (None,443) or parsed.username or parsed.password:raise ValueError('Public registry redirected outside allowed HTTPS hosts')
  redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
  if parsed.hostname!='ghcr.io':redirected.remove_header('Authorization')
  return redirected

def fetch(client,url,headers=None,limit=128*1024,destination=None):
 digest=hashlib.sha256();count=0;started=time.monotonic();output=bytearray()
 def deadline(signum,frame):raise TimeoutError('Public registry download deadline exceeded')
 previous=signal.signal(signal.SIGALRM,deadline);old_timer=signal.setitimer(signal.ITIMER_REAL,180)
 try:
  with client.open(urllib.request.Request(url,headers=headers or {}),timeout=35) as response:
   length=response.headers.get('Content-Length')
   if length and int(length)>limit:raise ValueError('Registry response exceeds size limit')
   while block:=response.read(512*1024):
    count+=len(block)
    if count>limit or time.monotonic()-started>180:raise ValueError('Registry response exceeds limits')
    digest.update(block)
    if destination:destination.write(block)
    else:output.extend(block)
  return bytes(output),digest.hexdigest()
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
  if old_timer[0]:signal.setitimer(signal.ITIMER_REAL,max(.001,old_timer[0]-(time.monotonic()-started)),old_timer[1])

def public_manifest():
 client=urllib.request.build_opener(urllib.request.ProxyHandler({}),PublicRegistryRedirect())
 raw,_=fetch(client,'https://ghcr.io/token?service=ghcr.io&scope=repository:aquasecurity/trivy-db:pull');token=json.loads(raw).get('token')
 if not isinstance(token,str) or not token:raise ValueError('Anonymous registry token unavailable')
 headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'};raw,digest=fetch(client,'https://ghcr.io/v2/aquasecurity/trivy-db/manifests/2',headers);manifest=json.loads(raw);layers=manifest.get('layers')
 if not isinstance(layers,list) or len(layers)!=1 or not re.fullmatch('sha256:[a-f0-9]{64}',layers[0].get('digest','')) or type(layers[0].get('size')) is not int or not 0<layers[0]['size']<=MAX_COMPRESSED:raise ValueError('Unsupported database manifest')
 return client,headers,{'digest':'sha256:'+digest,'layerDigest':layers[0]['digest'],'archiveSha256':layers[0]['digest'][7:],'compressedBytes':layers[0]['size']}

def load_manager():
 path=Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py'
 if path.is_symlink() or not path.is_file():raise ValueError('Installed VM controller unavailable')
 spec=importlib.util.spec_from_file_location('harness_database_update_manager',path);manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager);manager.validate();return manager

def guest_source(parameters):
 transaction=Path(__file__).with_name('security_db_transaction.py').read_text()
 import inspect
 unpack=inspect.getsource(unpack_verified)
 return transaction+'\nimport sys,gzip,tarfile,subprocess,shutil\nMAX_COMPRESSED='+str(MAX_COMPRESSED)+'\nMAX_DATABASE='+str(MAX_DATABASE)+'\n'+unpack+r'''
parameters=PARAMETERS
publisher_pins=PUBLISHER_PINS
if parameters['action']=='update':
 identity=parameters.get('identity') or {}
 if (identity.get('digest'),identity.get('layerDigest')) not in publisher_pins:
  raise ValueError('Database publisher evidence missing')

root=Path('/home/purge/tools/security-workbench');env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'}
if Path.home()!=Path('/home/purge') or root.resolve()!=root or (Path('/home/purge/.config/harness-vm-mode').read_text().strip()!='improved'):raise RuntimeError('Dedicated improved VM required')
def service(action):subprocess.run(['systemctl','--user',action,'dsh-original'],env=env,check=True,capture_output=True,timeout=40)
def idle():
 r=subprocess.run(['sudo','-n','/usr/bin/docker','ps','--filter','label=personal.harness.security=true','--format','{{.Names}}'],capture_output=True,text=True,check=True,timeout=8)
 if r.stdout.strip():return False
 import sqlite3
 engagements=Path('/home/purge/.dsh-improved/redteam/engagements')
 for file in engagements.glob('*/assets.db'):
  if file.resolve()!=file or file.is_symlink():raise RuntimeError('Unsafe project database')
  db=sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True,timeout=2)
  try:
   if db.execute("SELECT 1 FROM sqlite_master WHERE name='security_run'").fetchone() and db.execute("SELECT 1 FROM security_run WHERE state='running' LIMIT 1").fetchone():return False
  finally:db.close()
 return True
def validate():
 r=subprocess.run(['/home/purge/.local/node/bin/node','/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-runtime-preflight.mjs','--validating-update'],capture_output=True,text=True,timeout=15)
 return r.returncode==0 and json.loads(r.stdout).get('ok') is True
if parameters['action']=='status':
 manifest=json.loads(ordinary(root/'images.json',128*1024).read_text());record=None
 if os.path.lexists(root/'maintenance.json'):record=json.loads(ordinary(root/'maintenance.json',16384).read_text())
 print(json.dumps({'database':manifest['database'],'manifestSha256':digest(root/'images.json'),'maintenance':record,'idle':idle(),'ready':validate()}))
elif parameters['action']=='recover':
 print(json.dumps(recover(root,check_idle=idle,stop=lambda:service('stop'),start=lambda:service('start'))))
elif parameters['action']=='current':
 if os.path.lexists(root/'maintenance.json') or digest(root/'images.json')!=parameters['manifestSha256'] or not validate():raise RuntimeError('Current database not confirmed')
 result={'changed':False,'checkedAt':stamp(),'digest':parameters['digest'],'updatedAt':parameters['updatedAt']};write_json(root/'last-db-update.json',{'state':'current',**result});print(json.dumps(result))
else:
 if os.path.lexists(root/'maintenance.json') or digest(root/'images.json')!=parameters['manifestSha256']:raise RuntimeError('Database state changed; refusing import')
 inbox=root/('incoming-'+uuid.uuid4().hex);inbox.mkdir(mode=0o700);archive=inbox/'database.tar.gz';count=0
 with archive.open('xb') as out:
  while block:=sys.stdin.buffer.read(512*1024):
   count+=len(block)
   if count>MAX_COMPRESSED:raise ValueError('Incoming archive exceeds limit')
   out.write(block)
  out.flush();os.fsync(out.fileno())
 identity=unpack_verified(archive,inbox/'db',parameters['identity']['archiveSha256']);identity.update({key:parameters['identity'][key] for key in ['digest','layerDigest']})
 if any(identity[key]!=parameters['identity'][key] for key in ['fileSha256','fileBytes','metadata']):raise ValueError('Host and guest archive identity differ')
 archive.unlink();result=commit(root,inbox/'db',identity,check_idle=idle,stop=lambda:service('stop'),start=lambda:service('start'),validate=validate)
 if not result['changed']:
  for name in ['trivy.db','metadata.json']:(inbox/'db'/name).unlink()
  (inbox/'db').rmdir()
 inbox.rmdir();print(json.dumps(result))
'''.replace('PUBLISHER_PINS',repr(tuple(sorted(VERIFIED_DATABASE_PUBLISHER_PINS)))).replace('PARAMETERS',repr(parameters))

def query_guest(manager,parameters):
 result=manager.ssh('python3 -',input=guest_source(parameters),timeout=70)
 return json.loads(result.stdout)

def send_bundle(manager,parameters,archive):
 setup=manager.SETUP;code=guest_source(parameters)
 argv=['/usr/bin/ssh','-F','/dev/null','-p','49223','-i',str(setup/'guest-ed25519'),'-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+str(setup/'known_hosts')+'"','-o','GlobalKnownHostsFile=/dev/null','purge@127.0.0.1','python3 -c '+shlex.quote(code)]
 with Path(archive).open('rb') as stream:result=subprocess.run(argv,stdin=stream,capture_output=True,timeout=240,check=True)
 return json.loads(result.stdout)

def run_update(*,check_only=False,recover_last=False,manager=None):
 if sys.platform!='darwin':raise UpdateNotice('请从 Mac 统一启动器执行漏洞库维护。')
 manager=manager or load_manager()
 if recover_last:
  with manager.vm_operation('switch'):
   manager.validate()
   try:result=query_guest(manager,{'action':'recover'})
   finally:manager.start(quiet=True)
  return result
 current=query_guest(manager,{'action':'status'})
 if current['maintenance'] is not None:raise UpdateNotice('上次维护尚未结束，请先选择“恢复原漏洞库”，不要重复更新。')
 client,headers,remote=public_manifest();result={'checkedAt':datetime.now(timezone.utc).isoformat(),'installedDigest':current['database']['digest'],'registryDigest':remote['digest'],'sameRevision':current['database']['digest']==remote['digest'],'localReady':current['ready']}
 publisher_admitted=(remote['digest'],remote['layerDigest']) in VERIFIED_DATABASE_PUBLISHER_PINS
 result['publisherAdmission']='verified' if publisher_admitted else 'unverified'
 if check_only:return result
 if current['idle'] is not True:raise UpdateNotice('存在扫描或未确认任务，请先结束并核对任务，再更新漏洞库。')
 if result['sameRevision']:
  with manager.vm_operation('switch'):
   manager.validate();return query_guest(manager,{'action':'current','manifestSha256':current['manifestSha256'],'digest':remote['digest'],'updatedAt':current['database']['metadata']['UpdatedAt']})
 if not publisher_admitted:raise UpdateNotice('候选 Trivy 漏洞库缺少已验证的发布者证据，保留现用库。')
 print('下载并校验官方漏洞库；Harness 继续运行。',flush=True)
 with tempfile.TemporaryDirectory(prefix='harness-db-update-') as temporary:
  folder=Path(temporary).resolve();archive=folder/'database.tar.gz'
  with archive.open('xb') as out:_,sha=fetch(client,'https://ghcr.io/v2/aquasecurity/trivy-db/blobs/'+remote['layerDigest'],headers,limit=MAX_COMPRESSED,destination=out)
  if sha!=remote['archiveSha256'] or archive.stat().st_size!=remote['compressedBytes']:raise ValueError('Registry database content mismatch')
  identity=unpack_verified(archive,folder/'verified',remote['archiveSha256']);identity.update({key:remote[key] for key in ['digest','layerDigest']})
  if timestamp(identity['metadata']['UpdatedAt'])<timestamp(current['database']['metadata']['UpdatedAt']):raise ValueError('Registry returned an older database')
  print('校验完成。导入 VM，短暂停止 Harness 后替换数据库；失败将恢复原库。',flush=True)
  with manager.vm_operation('switch'):
   manager.validate()
   try:return send_bundle(manager,{'action':'update','manifestSha256':current['manifestSha256'],'identity':identity},archive)
   finally:manager.start(quiet=True)

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--recover-last',action='store_true');args=parser.parse_args(argv)
 try:
  result=run_update(check_only=args.check,recover_last=args.recover_last);print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except KeyboardInterrupt:print('更新已中断；请先在启动器选择检查或恢复，不会自动重试。');return 130
 except UpdateNotice as error:print(str(error));return 1
 except Exception:print('操作结果未确认。请保持 VM 运行，在启动器选择“检查/恢复漏洞库”；不会自动重试。');return 1

if __name__=='__main__':raise SystemExit(main())
