"""One bounded stdlib/file-only VM acceptance, not a target-program launcher."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import base64,fcntl,io,json,os,resource,selectors,signal,stat,subprocess,sys,time,zipfile

CAP=64*1024**2
STOP_RESERVE=4*1024**2
FLOOR=512*1024**2
LOG_LIMIT=1024**2
SOURCE_SHA='c6cbac0c9cd78102ac2335ff7dbfd48bd7c210baf2edf4a4e85e018df0ad1b0a'
BASELINE_SHA='fdeb973492f251cba0a9a7aaa0ee702afb76ba8c6b4768d057c6320b43880eb0'
GUEST=Path('/home/purge/workspace/harness-new-script-acceptance-20261113/stdlib-cli-readset-vm-acceptance-20261121-r1')

def require(ok,reason):
    if not ok:raise ValueError(reason)
def budget_admitted(used,free,planned):return used+planned+STOP_RESERVE<=CAP and free>=FLOOR+planned
def decode_files(rows):
    files={};total=0
    for name,row in rows.items():
        p=PurePosixPath(name)
        require(not p.is_absolute() and str(p)==name and bool(p.parts) and all(x not in ('.','..') for x in name.split('/')),'payload-path')
        raw=base64.b64decode(row['bytes'],validate=True);total+=len(raw)
        require(total<=8*1024**2 and sha256(raw).hexdigest()==row['sha256'],'payload-size-or-digest')
        files[name]=raw
    return files
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
def fingerprints(root,names):return {n:sha256((root/n).read_bytes()).hexdigest() for n in names}
def group_state(pgid):
    try:os.killpg(pgid,0)
    except ProcessLookupError:return 'absent'
    except PermissionError:return 'unknown'
    return 'present'
def child_limits():resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,8*1024**2))

def run_one(root,label,args,expected,immutable,seconds=120):
    root=Path(root);out=root/'evidence'/label
    require(label.replace('-','').isalnum() and not os.path.lexists(out),'existing-or-invalid-suite')
    require(0<seconds<=120 and args[0]==sys.executable and '-B' in args and not any(x in ('-O','-OO') for x in args),'interpreter-contract')
    v=os.statvfs(root);first_usage=usage(root);first_free=v.f_bavail*v.f_frsize
    require(budget_admitted(first_usage,first_free,8*1024**2),'suite-capacity-admission')
    out.mkdir(mode=0o700);before=fingerprints(root,immutable)
    write_json(out/'intent.json',{'suite':label,'command':args,'cwd':str(root/'candidate'),'expectedChecks':expected,'sourceAndScriptsBefore':before,'noAutomaticReplay':True,'createdBeforeProcess':True})
    env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',TMPDIR=str(root/'checks'))
    p=None;sel=selectors.DefaultSelector();streams={};counts={'stdout':0,'stderr':0};problem=None;start=time.monotonic();stop_at=None;code=None
    peak=first_usage;minimum=first_free;samples=1
    try:
        p=subprocess.Popen(args,cwd=root/'candidate',env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,preexec_fn=child_limits)
        write_json(out/'process.json',{'pid':p.pid,'processGroup':p.pid,'originalPopenChild':True})
        for pipe,name in [(p.stdout,'stdout'),(p.stderr,'stderr')]:
            sel.register(pipe,selectors.EVENT_READ,name);streams[name]=(out/(name+'.bin')).open('xb')
        while sel.get_map() or p.poll() is None:
            now=time.monotonic()
            if now-start>seconds:problem=problem or 'deadline'
            v=os.statvfs(root);sample=usage(root);free=v.f_bavail*v.f_frsize
            peak=max(peak,sample);minimum=min(minimum,free);samples+=1
            if sample>CAP-STOP_RESERVE or free<FLOOR:problem=problem or 'capacity-limit'
            if problem:
                stop_at=stop_at or now
                # Only signal the original still-live direct child group. A gone
                # leader/unknown descendant state is retained, never guessed away.
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
        problem=problem or type(error).__name__
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
    cleanup=p is None or (p.poll() is not None and group_state(p.pid)=='absent')
    if not cleanup:problem=problem or 'cleanup-unconfirmed'
    try:
        after=fingerprints(root,immutable)
        if before!=after:problem=problem or 'immutable-source-or-test-changed'
    except Exception as e:after=None;problem=problem or 'final-fingerprint-'+type(e).__name__
    result=None
    if not problem and code==0:
        try:
            raw=(out/'results.json').read_bytes();require(len(raw)<=LOG_LIMIT,'result-size')
            result=json.loads(raw);require(isinstance(result,dict),'result-object')
            rows=result.get('checks',result.get('results',[]));require(isinstance(rows,list) and all(isinstance(x,dict) for x in rows),'result-row-object')
            if not (type(result.get('passed')) is int and result['passed']==expected and type(result.get('total')) is int and result['total']==expected and len(rows)==expected and all(x.get('passed') is True for x in rows) and not result.get('failed')):problem='result-count-or-failed-case'
        except Exception:result=None;problem='result-missing-or-invalid'
    elif code!=0:problem=problem or 'suite-nonzero-exit'
    try:
        final_bytes=usage(root);v=os.statvfs(root);peak=max(peak,final_bytes);minimum=min(minimum,v.f_bavail*v.f_frsize);samples+=1
        if peak>CAP-STOP_RESERVE or minimum<FLOOR:problem=problem or 'capacity-limit'
    except Exception as e:final_bytes=None;problem=problem or 'final-usage-'+type(e).__name__
    record={'suite':label,'passed':problem is None and code==0,'problem':problem,'returncode':code,'expectedChecks':expected,'observedPassed':result.get('passed') if result else None,'observedTotal':result.get('total') if result else None,'sourceAndScriptsBefore':before,'sourceAndScriptsAfter':after,'immutableFilesUnchanged':before==after,'command':args,'cwd':str(root/'candidate'),'pid':p.pid if p else None,'cleanupConfirmed':cleanup,'elapsedSeconds':round(time.monotonic()-start,3),'outputBytes':counts,'vmTreeBytes':final_bytes,'peakTreeBytes':peak,'minFreeBytes':minimum,'capacitySamples':samples,'phaseCapBytes':CAP,'stopReserveBytesInsideCap':STOP_RESERVE,'actualVMApplicationWrites':True,'legacyVmWorkspaceWritesZeroNotUsedAsProof':True,'formalTargets':'0/16','r3':'blocked'}
    write_json(out/'capture.json',record);return record

def validate_runtime():
    require(os.getuid()==1000 and sys.platform=='linux' and not sys.flags.optimize,'dedicated-ordinary-Linux-account-required')
    require(sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()=='c86f21d0da9290ece2d7d49a3f7ed52aed59cb029abdf0ea25c79634f6cbe960','guest-interpreter-changed')
def process_identity():return {'pid':os.getpid(),'processStarttime':Path('/proc/self/stat').read_text().rpartition(') ')[2].split()[19]}
def validate_parent(path):require(path.resolve()==path and path.stat().st_uid==1000,'parent-path-identity')
def main(packet):
    validate_runtime();require(packet['guestRoot']==str(GUEST),'actual-guest-root-mismatch')
    require(not os.path.lexists(GUEST),'new-root-already-exists-query-original-only')
    # Validate the whole payload before creating any VM application file.
    files=decode_files(packet['files']);raw=files['candidate/protocol-manifest.json'];require(sha256(raw).hexdigest()==SOURCE_SHA,'candidate-manifest-changed')
    manifest=json.loads(raw);require(len(manifest['files'])==92,'candidate-count')
    for n,h in manifest['files'].items():require(sha256(files['candidate/'+n]).hexdigest()==h,'candidate-file-changed')
    baseline_raw=files['candidate/baseline/protocol-manifest.json'];require(sha256(baseline_raw).hexdigest()==BASELINE_SHA,'baseline-manifest-changed')
    baseline=json.loads(baseline_raw);require(len(baseline['files'])==87,'baseline-count')
    for n,h in baseline['files'].items():require(sha256(files['candidate/baseline/'+n]).hexdigest()==h,'baseline-file-changed')
    tests=packet['tests'];require(set(tests)=={'readset_checks.py','independent_gate_checks.py','proof_seven_checks.py','alias_checks.py'},'unexpected-test-set')
    require(set(files)=={'candidate/'+n for n in manifest['files']}|{'candidate/protocol-manifest.json'}|{'checks/'+n for n in tests}|{'candidate/baseline/'+n for n in baseline['files']}|{'candidate/baseline/protocol-manifest.json'},'unexpected-payload-file-set')
    for n,h in tests.items():require(sha256(files['checks/'+n]).hexdigest()==h,'test-digest-mismatch')
    v=os.statvfs(GUEST.parent);require(v.f_bavail*v.f_frsize>=FLOOR+CAP,'fresh-capacity-not-ready')
    validate_parent(GUEST.parent)
    GUEST.mkdir(mode=0o700);fd=os.open(GUEST/'.batch.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    rows=[];final_written=False;final=None
    try:
        identity=process_identity()
        (GUEST/'evidence').mkdir(mode=0o700);write_json(GUEST/'attempt.json',{'state':'staging',**identity,'guestRoot':str(GUEST),'sourceSha256':SOURCE_SHA,'expectedChecks':62,'admissionFreeBytes':v.f_bavail*v.f_frsize,'actualVMApplicationWrites':True,'noAutomaticReplay':True})
        for name,raw in files.items():
            target=GUEST/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            require(usage(GUEST)+len(raw)<=CAP-STOP_RESERVE,'staging-capacity-limit')
            out=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(out,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            require(sha256(target.read_bytes()).hexdigest()==sha256(raw).hexdigest(),'staging-readback')
        write_json(GUEST/'staging-verified.json',{'files':fingerprints(GUEST,files),'actualVMApplicationFilesWritten':len(files),'logicalInputBytes':sum(map(len,files.values())),'candidateFiles':92,'newScopeOnly':True})
        immutable=list(files);helper=str(GUEST/'candidate/checks/finalize_closure.py')
        descriptions=[('readset',11,'readset_checks.py',[]),('independent',29,'independent_gate_checks.py',['--helper',helper]),('proof',7,'proof_seven_checks.py',['--helper',helper]),('gate',13,None,[]),('alias',2,'alias_checks.py',[])]
        for name,count,script,extra in descriptions:
            output=str(GUEST/'evidence'/name/'results.json')
            if script:args=[sys.executable,'-B',str(GUEST/'checks'/script),*extra,'--out',output,'--tmp',str(GUEST/'checks'/(name+'-tmp'))]
            else:args=[sys.executable,'-B',str(GUEST/'candidate/checks/run_evidence_gate_checks.py'),'--tools',str(GUEST/'candidate/tools'),'--out',output]
            row=run_one(GUEST,name,args,count,immutable);rows.append(row)
            if not row['passed']:break
        final={'kind':'bounded-VM-readset-results','complete':len(rows)==5 and all(x['passed'] for x in rows),'suiteCount':len(rows),'expectedTotal':62,'observedTotal':sum(x['observedTotal'] or 0 for x in rows),'observedPassed':sum(x['observedPassed'] or 0 for x in rows),'vmTreeBytes':usage(GUEST),'rows':rows,'macOnlyNotApplicable':3,'actualVMApplicationWrites':True,'dailyDeploy':False,'formalTargets':'0/16','r3':'blocked'}
        write_json(GUEST/'final.json',final);final_written=True
    except BaseException as e:
        write_json(GUEST/'stopped.json',{'state':'incomplete','errorType':type(e).__name__,'reason':str(e)[:300],'pid':os.getpid(),'originalAttemptRetained':True,'noReplay':True})
    finally:
        os.fsync(fd);fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    stable=all(x.get('cleanupConfirmed') is True for x in rows)
    # An exception before run_one returns can leave an uncertain original child.
    # A controller-owned final is required before reading a bulk archive.
    if not final_written or not stable:
        return {'kind':'bounded-VM-readset-delivery','guestRoot':str(GUEST),'result':{'complete':False,'state':'stopped-or-cleanup-unknown'},'controllerFinalWritten':False,'archiveComplete':False,'collectionIssues':[{'reason':'controller-final-or-resource-quiescence-unconfirmed'}],'archiveBase64':None,'originalAttemptRetained':True,'formalTargets':'0/16','r3':'blocked'}
    collected=collect_artifacts(GUEST)
    return {'kind':'bounded-VM-readset-delivery','guestRoot':str(GUEST),'result':final,'controllerFinalWritten':True,**collected,'noHistoricalDirectoryCleanup':True,'formalTargets':'0/16','r3':'blocked'}

def collect_artifacts(root):
    members={};links={};issues=[];buffer=io.BytesIO();collected_bytes=0
    def error(e):issues.append({'path':str(Path(e.filename).relative_to(root)) if e.filename and Path(e.filename).is_relative_to(root) else 'tree','errorType':type(e).__name__})
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for directory,dirs,files in os.walk(root,followlinks=False,onerror=error):
            for entry in sorted(dirs+files):
                p=Path(directory)/entry;name=p.relative_to(root).as_posix()
                try:
                    s=p.lstat()
                    if stat.S_ISLNK(s.st_mode):links[name]=os.readlink(p)
                    elif stat.S_ISREG(s.st_mode):
                        require(name not in ('LINKS.json','ARCHIVE-ISSUES.json'),'reserved-archive-name')
                        require(s.st_size<=8*1024**2 and collected_bytes+s.st_size<=CAP-STOP_RESERVE,'export-member-or-total-limit')
                        raw=p.read_bytes();after=p.lstat()
                        require((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and len(raw)==s.st_size,'member-changed-during-archive')
                        z.writestr(name,raw);members[name]={'sha256':sha256(raw).hexdigest(),'bytes':len(raw)};collected_bytes+=len(raw)
                    elif not stat.S_ISDIR(s.st_mode):issues.append({'path':name,'errorType':'special-file'})
                except Exception as e:issues.append({'path':name,'errorType':type(e).__name__,'reason':str(e)[:180]})
        z.writestr('LINKS.json',json.dumps(links,sort_keys=True))
        z.writestr('ARCHIVE-ISSUES.json',json.dumps(issues,sort_keys=True))
    raw=buffer.getvalue()
    if len(raw)>CAP:issues.append({'path':'archive','errorType':'archive-limit'});raw=b''
    try:tree_bytes=usage(root)
    except Exception as e:tree_bytes=None;issues.append({'path':'tree','errorType':type(e).__name__})
    return {'archiveBytesPayload':raw,'archiveSha256':sha256(raw).hexdigest(),'members':members,'linksRecordedNotFollowed':links,'collectionIssues':issues,'archiveComplete':not issues,'VMTreeBytes':tree_bytes}

if __name__=='__main__':print(json.dumps(main(PACKET)))
