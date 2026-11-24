"""Host-only bounded trusted-check runner; derived functions pinned to prior reviewed controller."""
from pathlib import Path
from hashlib import sha256
import contextlib,fcntl,json,os,resource,selectors,signal,stat,subprocess,sys,time
CAP=64*1024**2
STOP_RESERVE=4*1024**2
FLOOR=512*1024**2
LOG_LIMIT=1024**2

def require(ok,reason):
    if not ok:raise ValueError(reason)

def error_reason(prefix,error):
    parts=[prefix,type(error).__name__]
    filename=getattr(error,'filename',None)
    if filename is not None:parts.append('filename='+str(filename))
    message=str(error)
    if message:parts.append('message='+message)
    return ':'.join(parts)

def budget_admitted(used,free,planned):return used+planned+STOP_RESERVE<=CAP and free>=FLOOR+planned

def write_json(path,value):
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

def usage(root):
    total=0
    def unreadable(error):
        path=Path(error.filename) if error.filename else None
        temporary=path is not None and any(path.is_relative_to(p) for p in (root/'checks',root/'candidate/checks/tmp'))
        if isinstance(error,FileNotFoundError) and temporary:return
        raise error
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=unreadable):
        for name in dirs+files:
            try:s=(Path(directory)/name).lstat()
            except FileNotFoundError:continue  # transient deletion by an owned fixture
            if stat.S_ISREG(s.st_mode):total+=s.st_size
    return total

def _check_sampling_lock_stat(st,identity=None):
    require(stat.S_ISREG(st.st_mode),'sampling-lock-regular')
    require(st.st_uid==os.getuid(),'sampling-lock-owner')
    require(st.st_nlink==1,'sampling-lock-links')
    if identity is not None:require((st.st_dev,st.st_ino)==identity,'sampling-lock-replaced')

def _open_sampling_lock(root):
    path=Path(root)/'.sampling.lock';path_stat=os.lstat(path)
    _check_sampling_lock_stat(path_stat)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fd_stat=os.fstat(fd);_check_sampling_lock_stat(fd_stat)
        identity=(fd_stat.st_dev,fd_stat.st_ino)
        require((path_stat.st_dev,path_stat.st_ino)==identity,'sampling-lock-replaced')
        return fd,identity
    except BaseException:
        os.close(fd);raise

def _verify_sampling_lock(root,fd,identity):
    path=Path(root)/'.sampling.lock';fd_stat=os.fstat(fd);path_stat=os.lstat(path)
    _check_sampling_lock_stat(fd_stat,identity);_check_sampling_lock_stat(path_stat,identity)
    require((fd_stat.st_dev,fd_stat.st_ino)==identity and (path_stat.st_dev,path_stat.st_ino)==identity,'sampling-lock-replaced')

def _sample_usage(root,expected=None):
    fd,identity=_open_sampling_lock(root)
    if expected is not None and identity!=expected:
        os.close(fd);raise ValueError('sampling-lock-replaced')
    locked=False
    try:
        try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:
            _verify_sampling_lock(root,fd,identity);return None
        locked=True
        _verify_sampling_lock(root,fd,identity)
        total=usage(root)
        _verify_sampling_lock(root,fd,identity)
        return total
    finally:
        try:
            if locked:fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

def sample_usage(root):return _sample_usage(root)

def _sample_retry(root,expected=None,timeout=2):
    deadline=time.monotonic()+timeout
    while True:
        value=_sample_usage(root,expected)
        if value is not None:return value
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('sampling-lock-timeout')
        time.sleep(min(.05,remaining))

def fingerprints(root,names):return {n:sha256((root/n).read_bytes()).hexdigest() for n in names}

def group_state(pgid):
    try:os.killpg(pgid,0)
    except ProcessLookupError:return 'absent'
    except PermissionError:return 'unknown'
    return 'present'

def child_limits():resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,8*1024**2))

def _identity_valid(value,pid):
    if not isinstance(value,dict):return False
    if type(value.get('pid')) is not int or value.get('pid')!=pid:return False
    if type(value.get('pgid')) is not int or value.get('pgid')!=pid:return False
    if value.get('groupLeader') is not True:return False
    if type(value.get('starttime')) is not int or value.get('starttime')<=0:return False
    if not isinstance(value.get('bootId'),str) or not value.get('bootId'):return False
    return True

def _identity_snapshot(value):
    return {key:value[key] for key in ('pid','pgid','starttime','bootId','groupLeader')}

def run_one(root,label,args,expected,immutable,seconds=120,result_file=None,validator=None,identity_reader=None):
    root=Path(root);out=root/'evidence'/label
    require(label.replace('-','').isalnum() and not os.path.lexists(out),'existing-or-invalid-suite')
    require(0<seconds<=120 and args[0]==sys.executable and '-B' in args and not any(x in ('-O','-OO') for x in args),'interpreter-contract')
    if identity_reader is not None and not callable(identity_reader):raise ValueError('identity-reader-not-callable')
    lock_path=root/'.sampling.lock';managed=os.path.lexists(lock_path);pinned=None;sampling_complete=0;sampling_paused=0;max_pause=0.0;pause_start=None
    if managed:
        fd,pinned=_open_sampling_lock(root);os.close(fd)
        first_usage=_sample_retry(root,pinned);sampling_complete+=1
    else:first_usage=usage(root)
    v=os.statvfs(root);first_free=v.f_bavail*v.f_frsize
    require(budget_admitted(first_usage,first_free,8*1024**2),'suite-capacity-admission')
    if validator is not None and not callable(validator):raise ValueError('validator-not-callable')
    if result_file is None:
        result_supplied=False;result_path=out/'results.json'
    else:
        result_supplied=True;result_path=Path(result_file)
        if not result_path.is_absolute():result_path=root/result_path
    root_abs=Path(os.path.abspath(root));chosen_abs=Path(os.path.abspath(result_path))
    try:relative=chosen_abs.relative_to(root_abs)
    except ValueError:raise ValueError('result-path-escape')
    current=root_abs
    if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):raise ValueError('result-path-symlink')
    for part in relative.parts:
        current=current/part
        if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):raise ValueError('result-path-symlink')
    if os.path.lexists(chosen_abs):raise ValueError('result-path-exists')
    result_path=chosen_abs
    out.mkdir(mode=0o700)
    if os.path.lexists(result_path):raise ValueError('result-path-exists')
    before=fingerprints(root,immutable)
    write_json(out/'intent.json',{'suite':label,'command':args,'cwd':str(root/'candidate'),'expectedChecks':expected,'sourceAndScriptsBefore':before,'noAutomaticReplay':True,'createdBeforeProcess':True,'identityRequired':identity_reader is not None})
    env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',TMPDIR=str(root/'checks'))
    p=None;sel=selectors.DefaultSelector();streams={};counts={'stdout':0,'stderr':0};problem=None;start=time.monotonic();stop_at=None;code=None
    peak=first_usage;minimum=first_free;samples=1
    identity=None;identity_reason=None;identity_write_error=None;identity_ok=False;identity_journal_ok=identity_reader is None
    try:
        p=subprocess.Popen(args,cwd=root/'candidate',env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,preexec_fn=child_limits)
        if identity_reader is None:
            try:
                write_json(out/'process.json',{'pid':p.pid,'processGroup':p.pid,'originalPopenChild':True})
                identity_journal_ok=True
            except BaseException as error:
                identity_journal_ok=False;identity_write_error=error_reason('process-journal',error);problem=problem or 'process-journal-write-failed'
        else:
            raw_identity=None
            try:raw_identity=identity_reader(p.pid)
            except BaseException as error:
                identity_reason=error_reason('identity-reader',error);problem=problem or 'identity-read-failed'
            else:
                if _identity_valid(raw_identity,p.pid):
                    identity=_identity_snapshot(raw_identity);identity_ok=True
                else:
                    identity_reason='identity-invalid';problem=problem or 'identity-invalid'
            process_record={'pid':p.pid,'processGroup':p.pid,'originalPopenChild':True,'identity':identity}
            if identity_reason is not None:process_record['identityReason']=identity_reason
            try:
                write_json(out/'process.json',process_record);identity_journal_ok=True
            except BaseException as error:
                identity_journal_ok=False;identity_write_error=error_reason('identity-journal',error);problem=problem or 'identity-journal-write-failed'
            if not identity_ok or not identity_journal_ok:problem=problem or 'identity-evidence-missing'
        for pipe,name in [(p.stdout,'stdout'),(p.stderr,'stderr')]:
            sel.register(pipe,selectors.EVENT_READ,name);streams[name]=(out/(name+'.bin')).open('xb')
        while sel.get_map() or p.poll() is None:
            now=time.monotonic()
            if now-start>seconds:problem=problem or 'deadline'
            v=os.statvfs(root);free=v.f_bavail*v.f_frsize;minimum=min(minimum,free)
            if managed:
                sample=_sample_usage(root,pinned)
                if sample is None:
                    sampling_paused+=1;now_busy=time.monotonic()
                    if pause_start is None:pause_start=now_busy
                    max_pause=max(max_pause,now_busy-pause_start)
                    if now_busy-pause_start>2:problem=problem or 'sampling-lock-timeout'
                else:
                    pause_start=None;sampling_complete+=1;peak=max(peak,sample);samples+=1
                    if sample>CAP-STOP_RESERVE:problem=problem or 'capacity-limit'
            else:
                sample=usage(root);peak=max(peak,sample);samples+=1
                if sample>CAP-STOP_RESERVE:problem=problem or 'capacity-limit'
            if free<FLOOR:problem=problem or 'capacity-limit'
            if problem:
                stop_at=stop_at or now
                if p.poll() is None and os.getpgid(p.pid)==p.pid:
                    try:os.killpg(p.pid,signal.SIGKILL if now-stop_at>=2 else signal.SIGTERM)
                    except ProcessLookupError:pass
                if now-stop_at>5:break
            for key,_ in sel.select(.05):
                block=os.read(key.fileobj.fileno(),65536)
                if not block:sel.unregister(key.fileobj);continue
                name=key.data
                if counts[name]+len(block)>LOG_LIMIT:problem=problem or 'output-limit'
                keep=block[:max(0,LOG_LIMIT-counts[name])];streams[name].write(keep);counts[name]+=len(keep)
        try:code=p.wait(timeout=3)
        except subprocess.TimeoutExpired:problem=problem or 'child-reap-unconfirmed'
    except BaseException as error:
        problem=problem or error_reason('run-error',error)
        if p is not None and p.poll() is None:
            try:
                if os.getpgid(p.pid)==p.pid:os.killpg(p.pid,signal.SIGTERM)
                code=p.wait(timeout=3)
            except (ProcessLookupError,subprocess.TimeoutExpired):pass
    finally:
        for f in streams.values():f.close()
        sel.close()
        for pipe in (() if p is None else (p.stdout,p.stderr)):
            if pipe is not None:pipe.close()
    if identity_reader is None:
        cleanup=p is None or (p.poll() is not None and group_state(p.pid)=='absent')
    else:
        if p is None:
            cleanup=False
        elif not (identity_ok and identity_journal_ok):
            cleanup=False
        else:
            state=group_state(p.pid)
            cleanup=p.poll() is not None and state=='absent'
            if state!='absent':problem=problem or ('cleanup-unconfirmed' if state=='present' else 'cleanup-unknown')
    if not cleanup:problem=problem or 'cleanup-unconfirmed'
    try:
        after=fingerprints(root,immutable)
        if before!=after:problem=problem or 'immutable-source-or-test-changed'
    except Exception as e:after=None;problem=problem or error_reason('final-fingerprint',e)
    result=None;validation_passed=None;validation_total=None
    if not problem and code==0:
        try:
            current=root_abs
            if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):raise ValueError('result-path-symlink')
            for part in result_path.relative_to(root_abs).parts:
                current=current/part
                if os.path.lexists(current) and stat.S_ISLNK(os.lstat(current).st_mode):raise ValueError('result-path-symlink')
            fd=os.open(result_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as f:
                st=os.fstat(f.fileno());require(stat.S_ISREG(st.st_mode),'result-regular');require(st.st_size<=LOG_LIMIT,'result-size')
                raw=f.read(LOG_LIMIT+1)
            require(len(raw)<=LOG_LIMIT,'result-size')
            result=json.loads(raw);require(isinstance(result,dict),'result-object')
            if validator is not None:
                try:checked=validator(result)
                except Exception as error:problem=error_reason('result-validator',error)
                else:
                    require(isinstance(checked,tuple) and len(checked)==2,'result-validator-tuple')
                    checked_passed,checked_total=checked
                    require(type(checked_passed) is int and type(checked_total) is int,'result-validator-int')
                    validation_passed=checked_passed;validation_total=checked_total
                    require(type(expected) is int and expected>0,'expected-count')
                    require(checked_passed==expected and checked_total==expected,'result-validator-count')
            else:
                rows=result.get('checks',result.get('results',[]));require(isinstance(rows,list) and all(isinstance(x,dict) for x in rows),'result-row-object')
                if not (type(result.get('passed')) is int and result['passed']==expected and type(result.get('total')) is int and result['total']==expected and len(rows)==expected and all(x.get('passed') is True for x in rows) and not result.get('failed')):problem='result-count-or-failed-case'
        except Exception as error:
            if problem is None:problem=error_reason('result-invalid',error)
            if validator is None or not isinstance(result,dict):result=None
    elif code!=0:problem=problem or 'suite-nonzero-exit'
    try:
        if managed:
            final_bytes=_sample_retry(root,pinned);sampling_complete+=1
        else:final_bytes=usage(root)
        v=os.statvfs(root);peak=max(peak,final_bytes);minimum=min(minimum,v.f_bavail*v.f_frsize);samples+=1
        if peak>CAP-STOP_RESERVE or minimum<FLOOR:problem=problem or 'capacity-limit'
    except TimeoutError as e:final_bytes=None;problem=problem or 'sampling-lock-timeout'
    except Exception as e:final_bytes=None;problem=problem or error_reason('final-usage',e)
    record={'suite':label,'passed':problem is None and code==0,'problem':problem,'returncode':code,'expectedChecks':expected,'observedPassed':result.get('passed') if result else None,'observedTotal':result.get('total') if result else None,'validationPassed':validation_passed,'validationTotal':validation_total,'resultPath':str(result_path),'resultFileSupplied':result_supplied,'validatorSupplied':validator is not None,'identityReaderSupplied':identity_reader is not None,'identity':identity,'identityValid':identity_ok,'identityReason':identity_reason,'identityJournalOk':identity_journal_ok,'identityJournalError':identity_write_error,'sourceAndScriptsBefore':before,'sourceAndScriptsAfter':after,'immutableFilesUnchanged':before==after,'command':args,'cwd':str(root/'candidate'),'pid':p.pid if p else None,'cleanupConfirmed':cleanup,'elapsedSeconds':round(time.monotonic()-start,3),'outputBytes':counts,'vmTreeBytes':final_bytes,'peakTreeBytes':peak,'minFreeBytes':minimum,'capacitySamples':samples,'samplingCompleteCount':sampling_complete,'samplingPausedCount':sampling_paused,'maxPauseSeconds':round(max_pause,3),'phaseCapBytes':CAP,'stopReserveBytesInsideCap':STOP_RESERVE,'hostApplicationWrites':True,'legacyVmWorkspaceWritesZeroNotUsedAsProof':True,'formalTargets':'0/16','r3':'blocked'}
    write_json(out/'capture.json',record);return record
