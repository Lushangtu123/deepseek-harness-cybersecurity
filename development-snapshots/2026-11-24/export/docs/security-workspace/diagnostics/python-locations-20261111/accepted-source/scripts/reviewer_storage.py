"""Trusted VM-local review storage policy and maintenance.

Loaded only from the tool installation; snapshot identity binds these bytes.
This module never grants host permissions or promotes evaluation eligibility.
"""
DEFAULT_BUDGET_BYTES = 256 * 1024 * 1024
RESERVATION_OVERHEAD_BYTES = 96 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
PLAN_TTL_SECONDS = 15 * 60
RECYCLE_MIN_SECONDS = 7 * 86400
MAX_ARCHIVE_ATTEMPTS = 8
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024

import os
import re
import stat
import json
import shutil
import fcntl
import uuid
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from contextlib import contextmanager

ID = re.compile(r'[0-9a-f]{32}')
MAX_STATE_BYTES = 16 * 1024 * 1024

class StorageError(ValueError):
    def __init__(self, code, *, retryable=False, details=None):
        self.code=code;self.retryable=retryable;self.details=details or {}
        super().__init__(code)


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def now():return datetime.now(timezone.utc).isoformat()


def policy_for(cache, overrides=None):
    cache=Path(cache)
    if cache.resolve()!=cache or not cache.is_absolute():raise ValueError('canonical cache required')
    overrides={} if overrides is None else overrides
    if not isinstance(overrides,dict) or not set(overrides)<= {'budgetBytes','minFreeBytes'}:raise ValueError('invalid storage policy overrides')
    budget=overrides.get('budgetBytes',DEFAULT_BUDGET_BYTES);minimum=overrides.get('minFreeBytes',MIN_FREE_BYTES)
    if type(budget) is not int or budget<=0 or type(minimum) is not int or minimum<0:raise ValueError('invalid storage budget')
    control=cache.parent/('.harness-storage-'+sha256(str(cache).encode()).hexdigest()[:16])
    return {'version':1,'uid':os.geteuid(),'cacheRoot':str(cache),'controlRoot':str(control),
            'budgetBytes':budget,'minFreeBytes':minimum,'reservationOverheadBytes':RESERVATION_OVERHEAD_BYTES,'minimumAgeDays':0,'recycleSeconds':RECYCLE_MIN_SECONDS,
            'planTtlSeconds':PLAN_TTL_SECONDS,'maxArchiveAttempts':MAX_ARCHIVE_ATTEMPTS,'maxArchiveBytes':MAX_ARCHIVE_BYTES}


def validate_policy(policy):
    numbers=['version','uid','budgetBytes','minFreeBytes','reservationOverheadBytes','minimumAgeDays','recycleSeconds','planTtlSeconds','maxArchiveAttempts','maxArchiveBytes']
    if (not isinstance(policy,dict) or not isinstance(policy.get('cacheRoot'),str)
            or any(type(policy.get(k)) is not int for k in numbers) or policy!=policy_for(policy.get('cacheRoot',''),
            {k:policy[k] for k in ['budgetBytes','minFreeBytes'] if k in policy})):raise ValueError('invalid storage policy')
    return policy


def existing_policy(cache):
    default=policy_for(cache);path=Path(default['controlRoot'])/'policy.json'
    value=validate_policy(read_json(path)) if path.exists() else default
    if value['cacheRoot']!=default['cacheRoot'] or value['controlRoot']!=default['controlRoot']:raise ValueError('storage policy location mismatch')
    return value


def private(path, create=False):
    path=Path(path)
    if path.resolve()!=path:raise ValueError('linked control directory')
    if create:path.mkdir(mode=0o700,exist_ok=True)
    value=path.lstat()
    if path.resolve()!=path:raise ValueError('linked control directory')
    if not stat.S_ISDIR(value.st_mode) or value.st_uid!=os.geteuid() or value.st_mode&0o077:raise ValueError('private owned directory required')
    if create:sync_directory(path);sync_directory(path.parent)
    return path


def read_bytes(path, limit=MAX_STATE_BYTES, root_cid=False):
    path=Path(path)
    if path.resolve()!=path:raise ValueError('linked storage file')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        value=os.fstat(stream.fileno())
        allowed=value.st_uid==os.geteuid() or root_cid and value.st_uid==0
        if not stat.S_ISREG(value.st_mode) or value.st_nlink!=1 or not allowed:raise ValueError('ordinary owned storage file required')
        if value.st_size>limit:raise ValueError('storage file too large')
        raw=stream.read(value.st_size);after=os.fstat(stream.fileno())
        if len(raw)!=value.st_size or (value.st_size,value.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('storage file changed')
    if len(raw)>limit:raise ValueError('storage file too large')
    return raw


def read_json(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate storage key')
            result[key]=value
        return result
    def constant(value):raise ValueError('nonfinite storage JSON')
    try:value=json.loads(read_bytes(path).decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)
    except RecursionError:raise ValueError('storage JSON nesting limit') from None
    pending=[(value,0)]
    while pending:
        item,depth=pending.pop()
        if depth>64:raise ValueError('storage JSON nesting limit')
        if isinstance(item,float) and (item!=item or abs(item)==float('inf')):raise ValueError('nonfinite storage JSON')
        if isinstance(item,dict):pending.extend((v,depth+1) for v in item.values())
        elif isinstance(item,list):pending.extend((v,depth+1) for v in item)
    return value


def atomic(path, value):
    path=Path(path);raw=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode()
    if len(raw)>MAX_STATE_BYTES:raise ValueError('storage record too large')
    temporary=path.parent/('.write-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary.exists():temporary.unlink()


@contextmanager
def capacity_lock(policy):
    validate_policy(policy)
    parent=Path(policy['cacheRoot']).parent
    if parent.resolve()!=parent:raise ValueError('linked cache parent')
    parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    control=private(policy['controlRoot'],True)
    fd=os.open(control/'capacity.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        value=os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_uid!=os.geteuid() or value.st_mode&0o077 or value.st_nlink!=1:raise ValueError('invalid capacity lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise StorageError('storage-busy',retryable=True) from None
        yield control
    finally:os.close(fd)


def state_locked(policy):
    control=private(policy['controlRoot']);saved=control/'policy.json'
    if saved.exists():
        if read_json(saved)!=policy:raise StorageError('storage-policy-changed')
    else:atomic(saved,policy)
    for name in ['outcomes','transactions','archives','recycle','index']:private(control/name,True)
    path=control/'ledger.json';ledger=read_json(path) if path.exists() else {'version':1,'active':{}}
    if not isinstance(ledger,dict) or type(ledger.get('version')) is not int or ledger.get('version')!=1 or not isinstance(ledger.get('active'),dict) or len(ledger['active'])>1000:raise ValueError('invalid reservation ledger')
    for key,row in ledger['active'].items():
        if (not isinstance(key,str) or not ID.fullmatch(key) or not isinstance(row,dict) or row.get('id')!=key
                or row.get('policySha256')!=digest(policy) or type(row.get('bytes')) is not int
                or type(row.get('inputBytes')) is not int or row['inputBytes']<0 or row['bytes']!=row['inputBytes']+RESERVATION_OVERHEAD_BYTES
                or row.get('directory')!=str(Path(policy['cacheRoot'])/('review-'+key))):raise ValueError('invalid reservation')
    return ledger


@contextmanager
def task_lock(path, shared=False, location=None):
    path=private(path);fd=os.open(path/'operation.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        value=os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_uid!=os.geteuid() or value.st_mode&0o077 or value.st_nlink!=1:raise ValueError('invalid task lock')
        try:fcntl.flock(fd,(fcntl.LOCK_SH if shared else fcntl.LOCK_EX)|fcntl.LOCK_NB)
        except BlockingIOError:raise StorageError('task-busy',retryable=True) from None
        def unchanged():
            current=((location[0] if location is not None else path)/'operation.lock').stat()
            if (current.st_dev,current.st_ino)!=(value.st_dev,value.st_ino):raise ValueError('task lock changed')
        yield unchanged
        unchanged()
    finally:os.close(fd)


def logical_bytes(path, counter=None, depth=0):
    counter=[0] if counter is None else counter
    before=path.stat();total=0
    if depth>24:raise StorageError('capacity-unavailable',details={'reason':'depth-limit'})
    for entry in path.iterdir():
        counter[0]+=1
        if counter[0]>20000:raise StorageError('capacity-unavailable',details={'reason':'entry-limit'})
        value=entry.lstat()
        if stat.S_ISLNK(value.st_mode) or value.st_dev!=before.st_dev:raise StorageError('capacity-unavailable',details={'reason':'linked-or-mounted-entry'})
        if stat.S_ISDIR(value.st_mode):
            if value.st_uid!=os.geteuid():raise StorageError('capacity-unavailable')
            total+=logical_bytes(entry,counter,depth+1)
        elif stat.S_ISREG(value.st_mode) and value.st_nlink==1:total+=value.st_size
        else:raise StorageError('capacity-unavailable',details={'reason':'special-entry'})
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_mtime_ns):raise StorageError('capacity-unavailable',retryable=True)
    return total


def settled_job(job):
    cleanup=job.get('cleanup',{})
    return (job.get('state') in {'completed','failed','timed-out','interrupted','recovered'}
            and isinstance(cleanup,dict) and cleanup.get('confirmed') is True and cleanup.get('errors')==[]
            and (all(cleanup.get(k) is True for k in ['idAbsent','nameAbsent','clientsStopped','creationResolved'])
                 or cleanup.get('noClientStarted') is True and job.get('creationAttempted') is False))


def usage_locked(policy, ledger, api):
    cache=Path(policy['cacheRoot']);used=sum(row['bytes'] for row in ledger['active'].values())
    if not cache.exists():return used
    private(cache)
    if cache.stat().st_dev!=cache.parent.stat().st_dev:raise StorageError('capacity-unavailable',details={'reason':'cross-device-cache'})
    entries=[]
    for entry in cache.iterdir():
        if len(entries)>=1000:raise StorageError('capacity-unavailable',details={'reason':'attempt-limit'})
        entries.append(entry)
    counter=[0]
    for entry in entries:
        if not re.fullmatch(r'review-[0-9a-f]{32}',entry.name) or entry.is_symlink():raise StorageError('capacity-unavailable')
        if entry.name[7:] in ledger['active']:continue
        try:
            outcome=Path(policy['controlRoot'])/'outcomes'/f'{entry.name[7:]}.json'
            if outcome.exists():
                proof=read_json(outcome);info=entry.stat()
                if (isinstance(proof,dict) and proof.get('id')==entry.name[7:] and proof.get('state')=='known-preparation-failure' and proof.get('sourceIdentity')==[info.st_dev,info.st_ino]
                        and not (entry/'attempt.json').exists() and not (entry/'container.cid').exists()):
                    used+=logical_bytes(entry,counter);continue
            with task_lock(entry,True):
                _,job=api._load_attempt(entry)
                if not settled_job(job):raise StorageError('capacity-unavailable',details={'reason':'unsettled-task','directory':str(entry)})
                used+=logical_bytes(entry,counter)
        except (OSError,ValueError) as error:
            if isinstance(error,StorageError):raise
            raise StorageError('capacity-unavailable',details={'directory':str(entry)}) from error
    return used


def reserve(policy, identity, input_bytes, api):
    validate_policy(policy)
    if not isinstance(identity,str) or not ID.fullmatch(identity) or type(input_bytes) is not int or input_bytes<0:raise ValueError('invalid reservation request')
    amount=input_bytes+RESERVATION_OVERHEAD_BYTES
    with capacity_lock(policy):
        ledger=state_locked(policy)
        if (Path(policy['controlRoot'])/'outcomes'/f'{identity}.json').exists():raise StorageError('reservation-already-settled')
        if identity in ledger['active']:
            row=ledger['active'][identity]
            if row.get('inputBytes')!=input_bytes:raise StorageError('reservation-identity-conflict')
            return row
        if (Path(policy['controlRoot'])/'outcomes'/f'{identity}.json').exists():raise StorageError('reservation-already-settled')
        if len(ledger['active'])>=1000:raise StorageError('reservation-limit')
        for previous in list(ledger['active']):
            settle_locked(policy,previous,ledger,api)
            ledger=state_locked(policy) # replace may have committed despite fsync error
        used=usage_locked(policy,ledger,api)
        if used+amount>policy['budgetBytes']:raise StorageError('cache-budget-exceeded',details={'accountedBytes':used,'requestedBytes':amount,'budgetBytes':policy['budgetBytes']})
        outstanding=sum(row['bytes'] for row in ledger['active'].values())
        cache=Path(policy['cacheRoot'])
        if shutil.disk_usage(cache if cache.exists() else cache.parent).free<policy['minFreeBytes']+outstanding+amount:raise StorageError('filesystem-space-insufficient')
        row={'id':identity,'directory':str(Path(policy['cacheRoot'])/('review-'+identity)),'inputBytes':input_bytes,
             'bytes':amount,'policySha256':digest(policy),'createdAt':now(),'controllerPid':os.getpid()}
        ledger['active'][identity]=row;atomic(Path(policy['controlRoot'])/'ledger.json',ledger)
        return row


def cancel_preparation(policy, identity):
    validate_policy(policy)
    if not isinstance(identity,str) or not ID.fullmatch(identity):raise ValueError('invalid preparation identity')
    private(Path(policy['controlRoot'])/'outcomes')
    # The live controller knows the engine was never reachable. Persist that
    # positive proof before trying the capacity mutex; a busy mutex must not
    # turn a known preparation failure into a permanently unknown reservation.
    path=Path(policy['cacheRoot'])/('review-'+identity)
    if path.is_symlink() or any((path/name).exists() or (path/name).is_symlink() for name in ['attempt.json','container.cid']):raise StorageError('preparation-state-unconfirmed')
    source=None
    if path.exists():
        private(path);logical_bytes(path);info=path.stat();source=[info.st_dev,info.st_ino]
    atomic(Path(policy['controlRoot'])/'outcomes'/f'{identity}.json',{'id':identity,'state':'known-preparation-failure','sourceIdentity':source,'finishedAt':now()})
    with capacity_lock(policy):
        ledger=state_locked(policy);row=ledger['active'].get(identity)
        if row is None:return
        del ledger['active'][identity];atomic(Path(policy['controlRoot'])/'ledger.json',ledger)


def settle_locked(policy, identity, ledger, api):
    row=ledger['active'].get(identity)
    if row is None:return True
    path=Path(row['directory'])
    try:
        if not (path/'attempt.json').exists():
            proof=read_json(Path(policy['controlRoot'])/'outcomes'/f'{identity}.json')
            if not isinstance(proof,dict) or proof.get('state')!='known-preparation-failure' or proof.get('id')!=identity:return False
            if (path/'attempt.json').is_symlink() or (path/'container.cid').exists() or (path/'container.cid').is_symlink():return False
            source=None
            if path.exists():
                private(path);logical_bytes(path);info=path.stat();source=[info.st_dev,info.st_ino]
            if proof.get('sourceIdentity')!=source:return False
            updated={'version':1,'active':{key:value for key,value in ledger['active'].items() if key!=identity}}
            atomic(Path(policy['controlRoot'])/'ledger.json',updated);ledger.clear();ledger.update(updated)
            return True
        with task_lock(path) as unchanged:
            _,job=api._load_attempt(path)
            reservation=job.get('storageReservation')
            if not settled_job(job) or not isinstance(reservation,dict) or reservation.get('id')!=identity:return False
            record_sha=sha256(read_bytes(path/'attempt.json')).hexdigest()
            unchanged()
            atomic(Path(policy['controlRoot'])/'outcomes'/f'{identity}.json',{'id':identity,'state':'settled','recordSha256':record_sha,'finishedAt':now()})
            updated={'version':1,'active':{key:value for key,value in ledger['active'].items() if key!=identity}}
            atomic(Path(policy['controlRoot'])/'ledger.json',updated)
            ledger.clear();ledger.update(updated)
            return True
    except (OSError,ValueError):return False


def settle(policy, identity, api):
    with capacity_lock(policy):return settle_locked(policy,identity,state_locked(policy),api)


def reconcile(policy, api, *,clock=None):
    with capacity_lock(policy):
        ledger=state_locked(policy);settled=[]
        for identity in list(ledger['active']):
            if settle_locked(policy,identity,ledger,api):settled.append(identity)
            ledger=state_locked(policy)
        report={'version':1,'settled':settled,'retained':list(ledger['active'].values()),
                'reservedBytes':sum(row['bytes'] for row in ledger['active'].values()),'noExpiryRelease':True,
                'cleanupCandidates':[],'transactionUnknown':[],'deleteEnabled':False}
        report['cleanupCandidates']=cleanup_inventory(policy,clock,report['transactionUnknown'])
        try:report['accountedBytes']=usage_locked(policy,ledger,api);report['capacityState']='known'
        except (OSError,ValueError) as error:report['capacityState']='unknown';report['capacityReason']=str(error)
        return report

# Archive implementation is installed tool code, never imported from a plan or
# project. Paths below are derived from validated policy and hexadecimal IDs.
import tarfile
import io
import ctypes

TOOL_VERSION='controlled-storage-v2'

def producer(api):
    return {'version':TOOL_VERSION,'launcherSha256':sha256(read_bytes(Path(api.__file__))).hexdigest(),
            'storageSha256':sha256(read_bytes(Path(__file__))).hexdigest()}


def signature(value):
    return {'device':value.st_dev,'inode':value.st_ino,'mode':stat.S_IMODE(value.st_mode),'uid':value.st_uid,
            'gid':value.st_gid,'links':value.st_nlink,'bytes':value.st_size,'mtimeNs':value.st_mtime_ns}


def bounded_names(path,limit):
    names=[]
    with os.scandir(path) as entries:
        for entry in entries:
            if len(names)>=limit:raise ValueError('directory entry limit')
            names.append(entry.name)
    return sorted(names)


class ReadBudget:
    def __init__(self,limit=MAX_ARCHIVE_BYTES):self.used=0;self.limit=limit
    def charge(self,length):
        if length<0 or self.used+length>self.limit:raise StorageError('archive-read-limit')
        self.used+=length


def source_snapshot(path, original, api, budget):
    """Bounded flat known artifacts only; hold the caller's existing task lock."""
    path=private(path);root_info=path.stat();files={};bodies={};names=[]
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        names=bounded_names(fd,20000)
        for name in names:
            value=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if value.st_dev!=root_info.st_dev:raise ValueError('cross-device source')
            item=signature(value)
            if name=='docker-config':
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    if value.st_uid!=os.geteuid() or value.st_mode&0o077 or bounded_names(child,1):raise ValueError('unsafe Docker configuration')
                    if signature(os.fstat(child))!=signature(value):raise ValueError('configuration changed')
                finally:os.close(child)
                files[name]={**item,'type':'directory'};continue
            known=name in {'attempt.json','operation.lock','container.cid'} or re.fullmatch(r'client-[1-9][0-9]{0,3}\.(stdout|stderr)',name)
            root_cid=name=='container.cid' and value.st_uid==0
            if (not known or not stat.S_ISREG(value.st_mode) or value.st_nlink!=1
                    or value.st_uid!=os.geteuid() and not root_cid
                    or (value.st_mode&0o022 if root_cid else value.st_mode&0o077)):raise ValueError('unsafe archive member')
            limit=MAX_STATE_BYTES if name=='attempt.json' else 2*1024*1024 if name.endswith('.stdout') else 65536 if name.endswith('.stderr') else 65 if name=='container.cid' else 0
            if value.st_size>limit:raise ValueError('oversized archive member')
            budget.charge(value.st_size)
            leaf=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            try:
                with os.fdopen(leaf,'rb') as stream:
                    before=os.fstat(stream.fileno())
                    if signature(before)!=item:raise ValueError('archive member changed')
                    raw=stream.read(value.st_size)
                    if len(raw)!=value.st_size or signature(os.fstat(stream.fileno()))!=item:raise ValueError('archive member changed')
            except Exception:raise
            bodies[name]=raw;files[name]={**item,'type':'file','sha256':sha256(raw).hexdigest()}
        if names!=bounded_names(fd,20000) or signature(os.fstat(fd))!=signature(root_info) or (path.stat().st_dev,path.stat().st_ino)!=(root_info.st_dev,root_info.st_ino):raise ValueError('source changed')
    finally:os.close(fd)
    if not {'attempt.json','operation.lock','docker-config'}<=set(files):raise ValueError('missing archive artifacts')
    job=api.load_json(bodies['attempt.json']);api._validate_attempt(Path(original),job)
    if not settled_job(job) or job.get('stageRemoved') is not True or job.get('cleanup',{}).get('creationResolved') is not True:raise ValueError('unsettled source')
    try:
        finished=datetime.fromisoformat(job['finishedAt'])
        if finished.tzinfo is None or finished>datetime.now(timezone.utc):raise ValueError('invalid terminal time')
    except (KeyError,TypeError):raise ValueError('invalid terminal time') from None
    cid=bodies.get('container.cid')
    if cid is not None:
        if not re.fullmatch(b'[0-9a-f]{64}\n?',cid) or cid.decode().strip()!=job.get('containerId'):raise ValueError('CID does not match record')
    elif job.get('containerId') is not None:raise ValueError('CID missing')
    count=job.get('clientCounter',0);clients=job.get('clients',[])
    if type(count) is not int or not 0<=count<=9999 or not isinstance(clients,list) or len(clients)>128:raise ValueError('invalid client inventory')
    if count>128 or job.get('clientHistoryTruncated') is True:raise ValueError('client history incomplete')
    if any(not isinstance(event,dict) or type(event.get('index')) is not int for event in clients):raise ValueError('invalid client record')
    if sorted(event['index'] for event in clients)!=list(range(1,count+1)):raise ValueError('client records incomplete or duplicated')
    expected={f'client-{i}.{extension}' for i in range(1,count+1) for extension in ['stdout','stderr']}
    actual={name for name in files if name.startswith('client-')}
    if actual!=expected:raise ValueError('client log inventory mismatch')
    for event in clients+([job['createClient']] if 'createClient' in job else []):
        if not isinstance(event,dict) or type(event.get('index')) is not int or not 1<=event['index']<=count:raise ValueError('invalid client record')
        if event.get('notStarted') is not True and (type(event.get('exitCode')) is not int or not isinstance(event.get('finishedAt'),str)):raise ValueError('client exit unconfirmed')
    result={'source':str(original),'rootIdentity':{'device':root_info.st_dev,'inode':root_info.st_ino,'uid':root_info.st_uid,'mode':stat.S_IMODE(root_info.st_mode)},
            'files':files,'recordSha256':sha256(bodies['attempt.json']).hexdigest(),'bytes':sum(map(len,bodies.values())),'originalState':job['state']}
    return result,bodies,job


def archive_plan(policy, api, *, attempt_ids=None, clock=None):
    validate_policy(policy);clock=datetime.now(timezone.utc) if clock is None else clock
    if not isinstance(clock,datetime) or clock.tzinfo is None:raise ValueError('aware plan time required')
    cache=private(policy['cacheRoot']);entries=[];retained=[];budget=ReadBudget();scanned=0
    if cache.stat().st_dev!=cache.parent.stat().st_dev:raise ValueError('cross-device cache')
    if attempt_ids is not None:
        if not isinstance(attempt_ids,list) or len(attempt_ids)>MAX_ARCHIVE_ATTEMPTS or len(set(attempt_ids))!=len(attempt_ids) or any(not isinstance(k,str) or not ID.fullmatch(k) for k in attempt_ids):raise ValueError('invalid archive selection')
        names=['review-'+key for key in attempt_ids]
    else:
        names=bounded_names(cache,1000)
    for name in names:
        if len(entries)>=MAX_ARCHIVE_ATTEMPTS:break
        scanned+=1;path=cache/name
        try:
            if not re.fullmatch(r'review-[0-9a-f]{32}',name):raise ValueError('unknown task name')
            if path.stat().st_dev!=cache.stat().st_dev:raise ValueError('cross-device task')
            # Never compete with a controller before its first record exists.
            if not (path/'attempt.json').is_file():raise ValueError('record unavailable')
            with task_lock(path,True):entry,_,_=source_snapshot(path,path,api,budget)
            # Reserve enough of the 64MiB apply read budget for two source
            # passes plus archive bytes and decoded verification. Conservative
            # batches can therefore contain less than 64MiB unique source data.
            estimate=4*sum(row['bytes'] for row in entries+[entry])+4096*sum(len(row['files']) for row in entries+[entry])+1024*1024
            if estimate>MAX_ARCHIVE_BYTES:raise ValueError('archive apply read budget; select smaller tasks')
            entries.append(entry)
        except (OSError,ValueError) as error:retained.append({'source':str(path),'reason':str(error)[:160]})
    value={'version':2,'id':uuid.uuid4().hex,'uid':os.geteuid(),'producer':producer(api),'policy':policy,
           'generatedAt':clock.isoformat(),'expiresAt':(clock.timestamp()+PLAN_TTL_SECONDS),'scanLimits':{'attempts':8,'contentBytes':MAX_ARCHIVE_BYTES,'entries':20000},
           'cacheIdentity':{'device':cache.stat().st_dev,'inode':cache.stat().st_ino},'scanned':scanned,'hashedBytes':budget.used,
           'entries':entries,'retained':retained,'readOnly':True,'deleteEnabled':False}
    encoded=json.dumps(value,allow_nan=False).encode()
    if len(encoded)>MAX_STATE_BYTES:raise ValueError('archive plan too large')
    return {**value,'planSha256':digest(value)}


def validate_plan(policy,plan,api,clock=None,expiry=True):
    validate_policy(policy)
    keys={'version','id','uid','producer','policy','generatedAt','expiresAt','scanLimits','cacheIdentity','scanned','hashedBytes','entries','retained','readOnly','deleteEnabled','planSha256'}
    if (not isinstance(plan,dict) or set(plan)!=keys or type(plan.get('version')) is not int or plan['version']!=2
            or not isinstance(plan.get('id'),str) or not ID.fullmatch(plan['id']) or type(plan.get('uid')) is not int or plan['uid']!=os.geteuid()
            or plan['policy']!=policy or plan['producer']!=producer(api) or plan['readOnly'] is not True or plan['deleteEnabled'] is not False
            or plan['planSha256']!=digest({k:v for k,v in plan.items() if k!='planSha256'})
            or plan['scanLimits']!={'attempts':8,'contentBytes':MAX_ARCHIVE_BYTES,'entries':20000}
            or not isinstance(plan['entries'],list) or not 0<len(plan['entries'])<=8):raise ValueError('invalid v2 archive plan')
    if (not isinstance(plan['generatedAt'],str) or type(plan['scanned']) is not int or not len(plan['entries'])<=plan['scanned']<=1000
            or type(plan['hashedBytes']) is not int or not 0<=plan['hashedBytes']<=MAX_ARCHIVE_BYTES
            or not isinstance(plan['cacheIdentity'],dict) or set(plan['cacheIdentity'])!={'device','inode'}
            or any(type(v) is not int or v<0 for v in plan['cacheIdentity'].values())
            or not isinstance(plan['retained'],list) or len(plan['retained'])>1000):raise ValueError('invalid plan metadata')
    for row in plan['retained']:
        if (not isinstance(row,dict) or set(row)!={'source','reason'} or not isinstance(row['source'],str)
                or Path(row['source']).parent!=Path(policy['cacheRoot']) or not isinstance(row['reason'],str)):raise ValueError('invalid retained entry')
    generated=datetime.fromisoformat(plan['generatedAt']);current=datetime.now(timezone.utc) if clock is None else clock
    if (generated.tzinfo is None or type(plan['expiresAt']) not in [int,float] or plan['expiresAt']!=generated.timestamp()+PLAN_TTL_SECONDS
            or expiry and not generated<=current<=datetime.fromtimestamp(plan['expiresAt'],timezone.utc)):raise ValueError('expired archive plan')
    seen=set()
    for entry in plan['entries']:
        if not isinstance(entry,dict) or not isinstance(entry.get('source'),str):raise ValueError('invalid archive entry')
        path=Path(entry['source']);identity=path.name.removeprefix('review-')
        if path!=Path(policy['cacheRoot'])/('review-'+identity) or not ID.fullmatch(identity) or identity in seen:raise ValueError('invalid source path')
        validate_manifest(entry,str(path))
        seen.add(identity)
    return plan


def rename_noreplace(source,destination):
    """Fixed libc no-replace rename. Fail closed if the OS lacks the primitive."""
    source=Path(source);destination=Path(destination)
    if source.parent.stat().st_dev!=destination.parent.stat().st_dev:raise ValueError('cross-device move')
    libc=ctypes.CDLL(None,use_errno=True)
    if os.uname().sysname=='Linux':
        call=libc.renameat2;call.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];call.restype=ctypes.c_int
        result=call(-100,os.fsencode(source),-100,os.fsencode(destination),1)
    elif os.uname().sysname=='Darwin':
        call=libc.renamex_np;call.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];call.restype=ctypes.c_int
        result=call(os.fsencode(source),os.fsencode(destination),4)
    else:raise ValueError('atomic no-replace rename unavailable')
    if result:raise OSError(ctypes.get_errno(),'no-replace rename failed',str(destination))
    for parent in {source.parent,destination.parent}:
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)


def transaction_paths(policy,txid,identity):
    if not ID.fullmatch(txid) or not ID.fullmatch(identity):raise ValueError('invalid transaction identity')
    control=Path(policy['controlRoot'])
    return {'source':str(Path(policy['cacheRoot'])/('review-'+identity)),
            'recycle':str(control/'recycle'/(txid+'-'+identity)),
            'archive':str(control/'archives'/(txid+'-'+identity+'.tar.gz'))}


def validate_manifest(manifest,source):
    if (not isinstance(manifest,dict) or set(manifest)!={'source','rootIdentity','files','recordSha256','bytes','originalState'}
            or manifest['source']!=source or not isinstance(manifest['files'],dict) or not 3<=len(manifest['files'])<=20000
            or type(manifest['bytes']) is not int or not 0<=manifest['bytes']<=MAX_ARCHIVE_BYTES
            or manifest['originalState'] not in {'completed','failed','timed-out','interrupted','recovered'}
            or not isinstance(manifest['recordSha256'],str) or not re.fullmatch('[0-9a-f]{64}',manifest['recordSha256'])):raise ValueError('invalid source manifest')
    files=manifest['files']
    root=manifest['rootIdentity']
    if (not isinstance(root,dict) or set(root)!={'device','inode','uid','mode'}
            or any(type(root[key]) is not int or root[key]<0 for key in root) or root['uid']!=os.geteuid() or root['mode']&0o077):raise ValueError('invalid root identity')
    if not {'attempt.json','operation.lock','docker-config'}<=set(files):raise ValueError('missing manifest members')
    for name,meta in files.items():
        known=name in {'attempt.json','operation.lock','container.cid','docker-config'} or re.fullmatch(r'client-[1-9][0-9]{0,3}\.(stdout|stderr)',name)
        if not known or not isinstance(meta,dict) or meta.get('type')!=('directory' if name=='docker-config' else 'file'):raise ValueError('unsafe manifest member')
        if set(meta)!=({'device','inode','mode','uid','gid','links','bytes','mtimeNs','type'}|({'sha256'} if meta['type']=='file' else set())):raise ValueError('invalid member fields')
        if any(type(meta.get(key)) is not int or meta[key]<0 for key in ['device','inode','mode','uid','gid','links','bytes','mtimeNs']):raise ValueError('invalid member identity')
        if meta['type']=='file' and (meta['links']!=1 or not isinstance(meta.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',meta['sha256'])):raise ValueError('invalid file fingerprint')
        root_cid=name=='container.cid' and meta['uid']==0
        if meta['device']!=root['device'] or meta['uid']!=os.geteuid() and not root_cid or (meta['mode']&0o022 if root_cid else meta['mode']&0o077):raise ValueError('unsafe member permissions')
    if sum(m['bytes'] for m in files.values() if m['type']=='file')!=manifest['bytes'] or files['attempt.json']['sha256']!=manifest['recordSha256']:raise ValueError('invalid manifest total')
    return manifest


def index_path(policy,identity):
    if not isinstance(identity,str) or not ID.fullmatch(identity):raise ValueError('invalid index identity')
    return Path(policy['controlRoot'])/'index'/(identity+'.json')


def load_transaction(policy,txid):
    if not isinstance(txid,str) or not ID.fullmatch(txid):raise ValueError('invalid transaction identity')
    folder=private(Path(policy['controlRoot'])/'transactions'/txid)
    tx=read_json(folder/'transaction.json')
    if (not isinstance(tx,dict) or type(tx.get('version')) is not int or tx.get('version')!=2 or tx.get('id')!=txid
            or tx.get('policySha256')!=digest(policy) or not isinstance(tx.get('entries'),list) or not 0<len(tx['entries'])<=8):raise ValueError('invalid transaction')
    seen=set()
    for row in tx['entries']:
        identity=row.get('identity') if isinstance(row,dict) else None
        if not isinstance(identity,str) or not ID.fullmatch(identity) or identity in seen or any(row.get(k)!=v for k,v in transaction_paths(policy,txid,identity).items()):raise ValueError('invalid transaction paths')
        if row.get('manifestSha256')!=digest(row.get('manifest')):raise ValueError('invalid transaction manifest')
        validate_manifest(row['manifest'],row['source'])
        seen.add(identity)
    return tx


def save_transaction(policy,tx):
    atomic(Path(policy['controlRoot'])/'transactions'/tx['id']/'transaction.json',tx)


def write_index(policy,tx,row):
    atomic(index_path(policy,row['identity']),{'version':2,'transactionId':tx['id'],'identity':row['identity'],'source':row['source'],
           'state':row['state'],'manifestSha256':row['manifestSha256'],'archiveSha256':row.get('archiveSha256')})


def create_archive(path,entry,bodies):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        with tarfile.open(fileobj=stream,mode='w:gz',format=tarfile.USTAR_FORMAT) as archive:
            for name,meta in sorted(entry['files'].items()):
                info=tarfile.TarInfo(name);info.mode=meta['mode'];info.uid=meta['uid'];info.gid=meta['gid'];info.mtime=meta['mtimeNs']//1000000000
                if meta['type']=='directory':info.type=tarfile.DIRTYPE;archive.addfile(info)
                else:info.size=len(bodies[name]);archive.addfile(info,io.BytesIO(bodies[name]))
        stream.flush();os.fsync(stream.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def verify_archive(row,budget):
    path=Path(row['archive']);size=path.lstat().st_size;budget.charge(size)
    raw=read_bytes(path,size)
    if len(raw)!=size:raise ValueError('archive size changed')
    actual=sha256(raw).hexdigest()
    if row.get('archiveSha256') and actual!=row['archiveSha256']:raise ValueError('archive digest mismatch')
    expected=row['manifest']['files'];seen=set();bodies={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        for member in archive:
            if member.name not in expected or member.name in seen or member.pax_headers:raise ValueError('unexpected archive member')
            seen.add(member.name);meta=expected[member.name]
            if member.mode!=meta['mode'] or member.uid!=meta['uid'] or member.gid!=meta['gid']:raise ValueError('archive metadata mismatch')
            if meta['type']=='directory':
                if not member.isdir() or member.size:raise ValueError('archive directory mismatch')
            else:
                if not member.isreg() or member.size!=meta['bytes']:raise ValueError('archive size mismatch')
                budget.charge(member.size);stream=archive.extractfile(member);body=stream.read(member.size+1)
                if len(body)!=member.size or sha256(body).hexdigest()!=meta['sha256']:raise ValueError('archive body mismatch')
                bodies[member.name]=body
    if seen!=set(expected):raise ValueError('incomplete archive')
    return actual,bodies


def archive_apply(policy,plan,api,*,probe=None,clock=None,fault=None):
    validate_plan(policy,plan,api,clock,False)
    with capacity_lock(policy):
        ledger=state_locked(policy);folder=Path(policy['controlRoot'])/'transactions'/plan['id']
        if folder.exists():
            tx=load_transaction(policy,plan['id'])
            if tx.get('planSha256')!=plan['planSha256']:raise ValueError('transaction identity conflict')
            return archive_status_locked(policy,tx,api)
        validate_plan(policy,plan,api,clock,True)
        cache=private(policy['cacheRoot']);info=cache.stat()
        if plan['cacheIdentity']!={'device':info.st_dev,'inode':info.st_ino}:raise ValueError('cache identity changed')
        if any(Path(policy['controlRoot'],name).stat().st_dev!=info.st_dev for name in ['recycle','archives','transactions','index']):raise ValueError('cross-device maintenance directory')
        folder.mkdir(mode=0o700);sync_directory(folder);sync_directory(folder.parent)
        budget=ReadBudget();tx={'version':2,'id':plan['id'],'policySha256':digest(policy),'planSha256':plan['planSha256'],'createdAt':now(),'entries':[]}
        for expected in plan['entries']:
            identity=Path(expected['source']).name[7:];paths=transaction_paths(policy,plan['id'],identity)
            tx['entries'].append({'identity':identity,**paths,'state':'prepared','manifest':expected,'manifestSha256':digest(expected)})
        save_transaction(policy,tx)
        for row in tx['entries']:
            source=Path(row['source']);location=[source]
            if row['identity'] in ledger['active']:raise StorageError('reservation-pending',retryable=True)
            previous=index_path(policy,row['identity'])
            if previous.exists() and read_json(previous).get('state') not in {'restored','not-moved'}:raise ValueError('source already indexed; query original transaction')
            with task_lock(source,location=location) as unchanged:
                entry,bodies,job=source_snapshot(source,source,api,budget)
                if entry!=row['manifest']:raise ValueError('source fingerprint changed')
                check=private(folder/row['identity'],True)
                proof=(probe or api.archive_probe)(check,source,job)
                if (not isinstance(proof,dict) or any(proof.get(k) is not True for k in ['confirmed','readOnly','containerAbsent','clientsStopped'])):raise ValueError('fresh resource check unconfirmed')
                row['resourceProof']=proof;row['state']='archiving';save_transaction(policy,tx)
                required=policy['minFreeBytes']+sum(r['bytes'] for r in ledger['active'].values())+entry['bytes']*2+len(entry['files'])*4096+MAX_STATE_BYTES
                if shutil.disk_usage(folder).free<required:raise StorageError('archive-filesystem-space-insufficient')
                create_archive(Path(row['archive']),entry,bodies)
                row['archiveSha256'],_=verify_archive(row,budget);row['state']='verified';save_transaction(policy,tx)
                if fault:fault('verified')
                latest,_,_=source_snapshot(source,source,api,budget)
                if latest!=entry:raise ValueError('source fingerprint changed before move')
                unchanged();row['state']='moving';row['moveStartedAt']=now();save_transaction(policy,tx);write_index(policy,tx,row)
                rename_noreplace(source,Path(row['recycle']));location[0]=Path(row['recycle'])
                if fault:fault('moved')
                row['state']='committed';row['committedAt']=now();row['retainUntil']=datetime.now(timezone.utc).timestamp()+RECYCLE_MIN_SECONDS
                save_transaction(policy,tx);write_index(policy,tx,row)
        tx['readBytes']=budget.used;save_transaction(policy,tx);return tx


def archive_status_locked(policy,tx,api):
    budget=ReadBudget()
    for row in tx['entries']:
        if row['state']=='moving':
            source=Path(row['source']);recycle=Path(row['recycle'])
            if source.exists() and not recycle.exists():
                with task_lock(source,True):entry,_,_=source_snapshot(source,source,api,budget)
                if entry!=row['manifest']:raise ValueError('pending source changed')
                row['state']='not-moved';save_transaction(policy,tx);write_index(policy,tx,row)
            elif not source.exists() and recycle.exists():
                verify_archive(row,budget)
                with task_lock(recycle,True):entry,_,_=source_snapshot(recycle,source,api,budget)
                if entry!=row['manifest']:raise ValueError('pending recycle changed')
                row['state']='committed';row['committedAt']=now();row['retainUntil']=datetime.now(timezone.utc).timestamp()+RECYCLE_MIN_SECONDS
                save_transaction(policy,tx);write_index(policy,tx,row)
            else:raise StorageError('archive-migration-unknown',details={'transactionId':tx['id']})
        elif row['state'] in {'prepared','archiving','verified'}:
            if not Path(row['source']).exists():raise StorageError('archive-migration-unknown',details={'transactionId':tx['id']})
            row['state']='not-moved';save_transaction(policy,tx)
    return tx


def archive_status(policy,txid,api):
    with capacity_lock(policy):state_locked(policy);return archive_status_locked(policy,load_transaction(policy,txid),api)


def archived_lookup(policy,source):
    identity=Path(source).name.removeprefix('review-');index=read_json(index_path(policy,identity));tx=load_transaction(policy,index['transactionId'])
    rows=[row for row in tx['entries'] if row['identity']==identity]
    if (len(rows)!=1 or rows[0]['source']!=str(source) or index.get('source')!=str(source)
            or type(index.get('version')) is not int or index['version']!=2 or index.get('identity')!=identity
            or index.get('manifestSha256')!=rows[0]['manifestSha256']):raise ValueError('archive index mismatch')
    row=rows[0]
    if row['state'] not in {'moving','committed','restoring'}:raise ValueError('original task unavailable')
    return {'state':'archived' if row['state']=='committed' else 'archive-pending','directory':str(source),'originalState':row['manifest']['originalState'],
            'transactionId':tx['id'],'archive':row['archive'],'recycle':row['recycle'],'recordSha256':row['manifest']['recordSha256'],
            'recordedOnly':True,'recoveryAction':'restore-required-no-analysis'}


def archive_restore(policy,txid,api,*,fault=None):
    with capacity_lock(policy):
        ledger=state_locked(policy);tx=archive_status_locked(policy,load_transaction(policy,txid),api);budget=ReadBudget()
        for row in tx['entries']:
            source=Path(row['source']);recycle=Path(row['recycle'])
            if row['state']=='restored':continue
            if row['state'] not in {'committed','restoring'}:raise ValueError('transaction is not archived')
            if source.exists() or source.is_symlink():
                if row['state']=='restoring':
                    # A previous no-replace rename may have committed. Verify
                    # original bytes before recording completion; never overwrite.
                    with task_lock(source,True):entry,_,_=source_snapshot(source,source,api,budget)
                    expected=row.get('restoreManifest',row['manifest'])
                    if entry!=expected:raise ValueError('restore destination conflict')
                    row['state']='restored';save_transaction(policy,tx);write_index(policy,tx,row);continue
                raise ValueError('restore destination exists')
            _,bodies=verify_archive(row,budget)
            used=usage_locked(policy,ledger,api);amount=row['manifest']['bytes']
            if used+amount>policy['budgetBytes']:raise StorageError('restore-cache-budget-exceeded')
            if shutil.disk_usage(Path(policy['cacheRoot'])).free<policy['minFreeBytes']+sum(r['bytes'] for r in ledger['active'].values())+amount+len(row['manifest']['files'])*4096+MAX_STATE_BYTES:raise StorageError('restore-filesystem-space-insufficient')
            if recycle.exists():work=recycle;expected=row['manifest']
            else:
                work=Path(policy['controlRoot'])/'recycle'/('restore-'+tx['id']+'-'+row['identity'])
                row['state']='restoring';row['restoreKind']='archive-copy';save_transaction(policy,tx);write_index(policy,tx,row)
                private(work,True)
                expected_names=set(row['manifest']['files'])
                if not set(bounded_names(work,20000))<=expected_names:raise ValueError('unexpected restore staging content')
                for name,meta in row['manifest']['files'].items():
                    target=work/name
                    if meta['type']=='directory':private(target,True);continue
                    if target.exists() or target.is_symlink():
                        if read_bytes(target,MAX_ARCHIVE_BYTES)!=bodies[name]:raise StorageError('restore-preparation-unconfirmed')
                        continue
                    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    with os.fdopen(fd,'wb') as stream:stream.write(bodies[name]);stream.flush();os.fsync(stream.fileno())
                    os.utime(target,ns=(meta['mtimeNs'],meta['mtimeNs']),follow_symlinks=False)
                with task_lock(work,True):expected,original,_=source_snapshot(work,source,api,budget)
                if original!=bodies:raise ValueError('restore staging bytes changed')
                sync_directory(work/'docker-config');sync_directory(work);sync_directory(work.parent)
                row['restoreManifest']=expected;save_transaction(policy,tx)
            location=[work]
            with task_lock(work,location=location) as unchanged:
                entry,original,_=source_snapshot(work,source,api,budget)
                if entry!=expected or original!=bodies:raise ValueError('recycle fingerprint changed')
                unchanged();row['state']='restoring';save_transaction(policy,tx);write_index(policy,tx,row)
                rename_noreplace(work,source);location[0]=source
                if fault:fault('restored')
                row['state']='restored';row['restoredAt']=now();save_transaction(policy,tx);write_index(policy,tx,row)
        return tx


def cleanup_inventory(policy,clock=None,unknown=None):
    clock=datetime.now(timezone.utc) if clock is None else clock;result=[];folder=Path(policy['controlRoot'])/'transactions'
    if not folder.exists():return result
    count=0
    for path in folder.iterdir():
        count+=1
        if count>1000:raise StorageError('transaction-scan-limit')
        if not ID.fullmatch(path.name):raise ValueError('unknown transaction directory')
        try:tx=load_transaction(policy,path.name)
        except (OSError,ValueError) as error:
            if unknown is not None:unknown.append({'transactionId':path.name,'reason':str(error)[:160],'retained':True})
            continue
        for row in tx['entries']:
            expiry=row.get('retainUntil')
            if row['state']=='committed' and type(expiry) in [int,float] and clock.timestamp()>=expiry:
                result.append({'transactionId':tx['id'],'identity':row['identity'],'recycle':row['recycle'],'archive':row['archive'],
                               'retainUntil':expiry,'action':'review-cleanup-list-only','safeToDelete':False})
    return result
