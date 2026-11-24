"""Guest-side exact-file transaction. No download, credentials or shell commands."""
from pathlib import Path
import fcntl,hashlib,json,os,re,stat,tempfile,uuid
from datetime import datetime,timezone,timedelta

def timestamp(value):
 if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})',value):raise ValueError('Invalid RFC3339 database time')
 try:return datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError:raise ValueError('Invalid database calendar time')

def validate_metadata(value,now=None):
 if not isinstance(value,dict) or type(value.get('Version')) is not int or value['Version']!=2:raise ValueError('Unsupported database schema')
 updated=timestamp(value.get('UpdatedAt'));next_at=timestamp(value.get('NextUpdate'));at=timestamp(now) if now else datetime.now(timezone.utc)
 if next_at<=updated or updated>at+timedelta(minutes=5):raise ValueError('Contradictory or future database metadata')
 return value

def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def ordinary(path,limit):
 path=Path(path)
 if path.resolve()!=path or path.is_symlink():raise ValueError('Unsafe database resource path')
 info=path.stat()
 if not stat.S_ISREG(info.st_mode) or info.st_size<1 or info.st_size>limit:raise ValueError('Invalid database resource file')
 return path

def atomic(path,raw,mode=0o600):
 path=Path(path)
 if path.is_symlink() or path.parent.resolve()!=path.parent:raise ValueError('Unsafe transaction target')
 fd,name=tempfile.mkstemp(dir=path.parent,prefix='.db-update-')
 try:
  with os.fdopen(fd,'wb') as stream:os.fchmod(stream.fileno(),mode);stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(name,path)
 finally:Path(name).unlink(missing_ok=True)

def stamp():return datetime.now(timezone.utc).isoformat()

def write_json(path,value):atomic(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())

def lease(root):
 fd=os.open(root/'.db-update.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BaseException:os.close(fd);raise RuntimeError('Database update is already running')
 return fd

def validate_identity(stage,identity):
 validate_metadata(identity.get('metadata'))
 db=ordinary(stage/'trivy.db',2*1024**3);meta=ordinary(stage/'metadata.json',16384)
 if not re.fullmatch('[a-f0-9]{64}',identity.get('fileSha256','')) or type(identity.get('fileBytes')) is not int or db.stat().st_size!=identity['fileBytes'] or digest(db)!=identity['fileSha256']:raise ValueError('Staged database hash mismatch')
 if json.loads(meta.read_text())!=identity.get('metadata') or not re.fullmatch('sha256:[a-f0-9]{64}',identity.get('digest','')):raise ValueError('Staged database identity mismatch')

def rollback(root,backup,journal):
 current=root/'cache/db';old=backup/'db';before=(backup/'before-manifest.json').read_bytes();manifest=root/'images.json'
 if hashlib.sha256(before).hexdigest()!=journal['beforeManifestSha256']:raise RuntimeError('Backup manifest changed')
 raw=ordinary(manifest,128*1024).read_bytes()
 if hashlib.sha256(raw).hexdigest() not in {journal['beforeManifestSha256'],journal['afterManifestSha256']}:raise RuntimeError('Manifest changed outside this update')
 if old.exists():
  if digest(ordinary(old/'trivy.db',2*1024**3))!=journal['beforeDatabaseSha256']:raise RuntimeError('Backup database changed')
  if current.exists():
   if digest(ordinary(current/'trivy.db',2*1024**3))!=journal['afterDatabaseSha256']:raise RuntimeError('Live database changed outside this update')
   os.replace(current,backup/'rejected-db')
  os.replace(old,current)
 elif not current.exists() or digest(ordinary(current/'trivy.db',2*1024**3))!=journal['beforeDatabaseSha256']:raise RuntimeError('Original database unavailable')
 atomic(manifest,before,journal['manifestMode']);journal['phase']='rolled-back';write_json(backup/'journal.json',journal)

def commit(root,stage,identity,*,check_idle,stop,start,validate):
 root=Path(root);stage=Path(stage)
 if root.resolve()!=root or stage.resolve()!=stage or not stage.is_relative_to(root):raise ValueError('Unsafe update directory')
 validate_identity(stage,identity);fd=lease(root)
 try:
  if os.path.lexists(root/'maintenance.json'):raise RuntimeError('An earlier update needs recovery before retry')
  if check_idle() is not True:raise RuntimeError('Scanner is active; database update refused')
  manifest=root/'images.json';before=ordinary(manifest,128*1024).read_bytes();original=json.loads(before);old=original['database'];live=root/'cache/db'
  if digest(ordinary(live/'trivy.db',2*1024**3))!=old['fileSha256']:raise RuntimeError('Existing database differs from recorded identity')
  if timestamp(identity['metadata']['UpdatedAt'])<timestamp(old['metadata']['UpdatedAt']):raise ValueError('Database downgrade refused')
  if identity['fileSha256']==old['fileSha256'] and identity['digest']==old['digest'] and identity['metadata']==old['metadata']:
   result={'changed':False,'checkedAt':stamp(),'digest':old['digest'],'updatedAt':old['metadata']['UpdatedAt']};write_json(root/'last-db-update.json',{'state':'current',**result});return result
  backups=root/'backups';backups.mkdir(exist_ok=True)
  if backups.resolve()!=backups:raise ValueError('Unsafe backup directory')
  backup=backups/uuid.uuid4().hex;backup.mkdir(mode=0o700);atomic(backup/'before-manifest.json',before)
  desired={**original,'database':{**identity,'ready':True}};after=(json.dumps(desired,indent=2)+'\n').encode()
  journal={'schemaVersion':1,'phase':'prepared','beforeManifestSha256':hashlib.sha256(before).hexdigest(),'afterManifestSha256':hashlib.sha256(after).hexdigest(),'beforeDatabaseSha256':old['fileSha256'],'afterDatabaseSha256':identity['fileSha256'],'manifestMode':stat.S_IMODE(manifest.stat().st_mode)};write_json(backup/'journal.json',journal)
  marker={'state':'updating','backup':backup.name,'startedAt':stamp()};write_json(root/'maintenance.json',marker);attempted=False;starting=False
  try:
   attempted=True;stop()
   if check_idle() is not True:raise RuntimeError('Scanner became active; update refused')
   os.replace(live,backup/'db');journal['phase']='old-db-backed-up';write_json(backup/'journal.json',journal)
   os.replace(stage,live);journal['phase']='new-db-installed';write_json(backup/'journal.json',journal)
   atomic(manifest,after,journal['manifestMode']);journal['phase']='manifest-installed';write_json(backup/'journal.json',journal)
   if validate() is not True:raise RuntimeError('Updated database validation failed')
   starting=True;start();journal['phase']='committed';write_json(backup/'journal.json',journal)
   result={'changed':True,'backup':str(backup),'checkedAt':stamp(),'digest':identity['digest'],'updatedAt':identity['metadata']['UpdatedAt']};write_json(root/'last-db-update.json',{'state':'updated',**result});(root/'maintenance.json').unlink();return result
  except BaseException as error:
   try:
    if starting:stop()
    rollback(root,backup,journal)
    if attempted:start()
    write_json(root/'last-db-update.json',{'state':'rolled-back','checkedAt':stamp(),'backup':str(backup)});(root/'maintenance.json').unlink()
   except BaseException as recovery:raise RuntimeError('Update failed; recovery needs inspection: '+str(backup)) from recovery
   raise RuntimeError('Update failed; original database restored') from error
 finally:os.close(fd)

def recover(root,*,check_idle,stop,start):
 root=Path(root);fd=lease(root)
 try:
  if check_idle() is not True:raise RuntimeError('Scanner is active; database recovery refused')
  marker=json.loads(ordinary(root/'maintenance.json',16384).read_text());name=marker.get('backup','')
  if not re.fullmatch('[a-f0-9]{32}',name):raise ValueError('Invalid recovery record')
  backup=root/'backups'/name;journal=json.loads(ordinary(backup/'journal.json',16384).read_text())
  if journal.get('schemaVersion')!=1 or any(not re.fullmatch('[a-f0-9]{64}',journal.get(key,'')) for key in ['beforeManifestSha256','afterManifestSha256','beforeDatabaseSha256','afterDatabaseSha256']) or type(journal.get('manifestMode')) is not int or not 0<=journal['manifestMode']<=0o777:raise ValueError('Invalid journal')
  stop()
  if check_idle() is not True:
   start();raise RuntimeError('Scanner became active; database recovery refused')
  rollback(root,backup,journal);start();(root/'maintenance.json').unlink();write_json(root/'last-db-update.json',{'state':'rolled-back','checkedAt':stamp(),'backup':str(backup)});return{'recovered':True,'backup':str(backup)}
 finally:os.close(fd)
