'''One admitted VM submission; a transport success alone is never acceptance.'''
from pathlib import Path,PurePosixPath
from hashlib import sha256
import base64,importlib.util,json,math,os,sys,stat,types
R=Path(__file__).resolve().parents[1]
CAP=64*1024**2
STOP_RESERVE=4*1024**2
FLOOR=512*1024**2
FROZEN_GUEST=Path('/home/purge/workspace/harness-new-script-acceptance-20261113/stdlib-cli-all20-fixture-lifecycle-20261124-r1')
def require(v,why):
    if not v:raise ValueError(why)
def load(name,path):
    path=Path(path)
    raw=path.read_bytes()
    m=types.ModuleType(name)
    m.__file__=str(path)
    exec(compile(raw,m.__file__,'exec'),m.__dict__)
    return m
def _hex64(v):
    return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)
def validate_transport(argv, timeout, input, *, expected_argv, expected_input_sha256, minimum_seconds):
    require(isinstance(expected_argv,list) and all(isinstance(x,str) for x in expected_argv),'transport-expected-argv')
    require(isinstance(argv,list) and all(isinstance(x,str) for x in argv) and argv==expected_argv,'transport-argv')
    require(_hex64(expected_input_sha256),'transport-expected-sha')
    require(isinstance(minimum_seconds,(int,float)) and not isinstance(minimum_seconds,bool) and math.isfinite(minimum_seconds) and minimum_seconds>=0,'transport-minimum')
    require(isinstance(timeout,(int,float)) and not isinstance(timeout,bool) and math.isfinite(timeout) and timeout>0 and timeout>=minimum_seconds,'transport-timeout')
    if isinstance(input,str):
        raw=input.encode('utf-8')
    elif isinstance(input,(bytes,bytearray,memoryview)):
        raw=bytes(input)
    else:
        raise ValueError('transport-input-type')
    require(sha256(raw).hexdigest()==expected_input_sha256,'transport-input-sha')
    return True
def _valid_rel(name):
    if not isinstance(name,str):return False
    p=PurePosixPath(name)
    return not p.is_absolute() and str(p)==name and bool(p.parts) and '..' not in p.parts
def _regular(path):
    try:info=os.lstat(path)
    except OSError:return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
def _no_symlink_components(base,rel):
    cur=Path(base)
    try:info=os.lstat(cur)
    except OSError:return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):return False
    for part in PurePosixPath(rel).parts:
        cur=cur/part
        try:info=os.lstat(cur)
        except OSError:return False
        if stat.S_ISLNK(info.st_mode):return False
    return True
def _read_json(path):
    with open(path,'rb') as f:return json.loads(f.read())
def _usage(root):
    total=0
    def fail(error):raise error
    info=os.lstat(root)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise ValueError('usage-special')
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=fail):
        for name in dirs:
            info=os.lstat(os.path.join(directory,name))
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise ValueError('usage-special')
        for name in files:
            info=os.lstat(os.path.join(directory,name))
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):raise ValueError('usage-special')
            total+=info.st_size
    return total
def _budget_ok(extra,stop=False):
    try:
        used=_usage(R)
        stats=os.statvfs(R)
        free=stats.f_bavail*stats.f_frsize
    except (OSError,ValueError):
        return False
    limit=CAP if stop else CAP-STOP_RESERVE
    return used+extra<=limit and free>=FLOOR+extra
def record(name,value,stop=False):
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+chr(10)).encode('utf-8')
    require(_budget_ok(len(raw),stop=stop),'host-budget')
    p=R/'evidence'/name
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
def validate_payload(packet,expected,root):
    require(isinstance(packet,dict) and isinstance(expected,dict),'payload-object')
    start=_read_json(root/'START.json')
    require(str(FROZEN_GUEST)==packet.get('guestRoot')==expected.get('guestRoot')==start.get('guestRoot'),'guest-root')
    require(packet.get('caseIds')==expected.get('caseIds'),'case-ids')
    if 'caseIds' in start:require(start.get('caseIds')==packet.get('caseIds'),'start-case-ids')
    source=packet.get('sourceManifestSha256')
    require(_hex64(source) and source==expected.get('sourceManifestSha256'),'source-manifest-sha')
    require(source==start.get('candidateManifestSha256'),'start-candidate-sha')
    files=packet.get('files');efiles=expected.get('files')
    require(isinstance(files,dict) and isinstance(efiles,dict),'payload-files')
    require(set(files)==set(efiles),'payload-file-set')
    for name,row in files.items():
        require(_valid_rel(name),'payload-path')
        require(isinstance(row,dict),'payload-row')
        try:raw=base64.b64decode(row['bytes'],validate=True)
        except Exception:raise ValueError('payload-base64')
        digest=sha256(raw).hexdigest()
        require(row.get('sha256')==digest,'payload-digest')
        erow=efiles.get(name)
        require(isinstance(erow,dict),'expected-row')
        require(erow.get('sha256')==digest,'expected-sha')
        size=erow.get('bytes',erow.get('size'))
        require(isinstance(size,int) and size==len(raw),'expected-size')
        require(_no_symlink_components(root,name),'payload-symlink')
        disk=root/name
        require(_regular(disk),'payload-disk-regular')
        require(disk.read_bytes()==raw,'payload-disk-bytes')
    require(expected.get('payloadSha256')==sha256((root/'payload.json').read_bytes()).hexdigest(),'payload-sha')
def _admission(packet,expected):
    a=_read_json(R/'source-admission.json')
    require(a.get('accepted') is True,'not-admitted')
    mandatory={'operator/run_vm.py','operator/verify_delivery.py','operator/transfer.py','operator/status_guest.py','operator/consumer_vm.py','operator/full20_batch.py','operator/suite-plan.json','operator/collect_independent.py','operator/bounded.py','operator/archive_helpers.py','operator/linux_admission.py','vm_read.py','payload.json','START.json','expected-cases.json','evidence/payload-manifest.json'}
    mandatory.update(packet['files'])
    require(mandatory<=set(a['files']),'incomplete-admission')
    for n,h in a['files'].items():
        require(_valid_rel(n),'admission-path')
        require(_no_symlink_components(R,n),'admission-symlink')
        require(_regular(R/n),'admission-file')
        require(sha256((R/n).read_bytes()).hexdigest()==h,'admission-changed:'+n)
    for n,row in packet['files'].items():
        require(a['files'].get(n)==row.get('sha256'),'packet-not-admitted:'+n)
    receipt=PurePosixPath(a['reviewReceipt'])
    require(_valid_rel(str(receipt)),'receipt-path')
    require(_no_symlink_components(R,str(receipt)),'receipt-symlink')
    require(_regular(R/receipt),'receipt-file')
    require(sha256((R/receipt).read_bytes()).hexdigest()==a['reviewReceiptSha256'],'review-changed')
    admitted_sha=packet.get('sourceManifestSha256')
    require(_hex64(admitted_sha),'binding-admitted-sha')
    binding=load('reviewed_full20_binding',R/'operator/full20_batch.py')
    require(hasattr(binding,'validate_binding') and callable(binding.validate_binding),'binding-callable')
    binding_plan=binding.validate_binding((R/'candidate/protocol-manifest.json').read_bytes(),(R/'operator/suite-plan.json').read_bytes(),admitted_sha)
    require(isinstance(binding_plan,dict) and binding_plan.get('sourceManifestSha256')==admitted_sha,'binding-source')
    return a
def _build_run_remote(packet):
    nl=chr(10)
    code=(R/'operator/consumer_vm.py').read_bytes()
    remote='PACKET='+repr(packet)+nl+code.decode()+nl
    remote+='import sys,types,base64'+nl
    remote+='_t=types.ModuleType('+repr('operator_transfer')+')'+nl
    remote+='exec(compile(base64.b64decode(PACKET['+repr('files')+']['+repr('operator/transfer.py')+']['+repr('bytes')+']),'+repr('<operator/transfer.py>')+','+repr('exec')+'),_t.__dict__)'+nl
    remote+='delivery=main(PACKET)'+nl
    remote+='_t.emit_frame(delivery,sys.stdout.buffer)'+nl
    compile(remote,'<fixed-consumer-controller>','exec')
    return remote,code
def _build_status_remote(packet,expected):
    nl=chr(10)
    code=(R/'operator/status_guest.py').read_bytes()
    remote='PACKET='+repr(packet)+nl+'EXPECTED='+repr(expected)+nl+code.decode()+nl
    remote+='import sys,types,base64'+nl
    remote+='_t=types.ModuleType('+repr('operator_transfer')+')'+nl
    remote+='exec(compile(base64.b64decode(PACKET['+repr('files')+']['+repr('operator/transfer.py')+']['+repr('bytes')+']),'+repr('<operator/transfer.py>')+','+repr('exec')+'),_t.__dict__)'+nl
    remote+='_t.emit_frame(main(EXPECTED),sys.stdout.buffer)'+nl
    compile(remote,'<fixed-status>','exec')
    return remote
def _expected_ssh_argv(manager):
    base=Path(manager.SETUP)
    return ['/usr/bin/ssh','-F','/dev/null','-p','49223','-i',str(base/'guest-ed25519'),'-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=3','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+str(base/'known_hosts')+'"','-o','GlobalKnownHostsFile=/dev/null','purge@127.0.0.1','/usr/bin/python3 -I -B -']
def _manager(prefix,transfer,expected_input_sha256=None,minimum_seconds=None):
    manager=load('pinned_consumer_transport',R/'vm_read.py').manager()
    expected_argv=_expected_ssh_argv(manager)
    used=[False]
    def adapter(argv,timeout=None,input=None):
        if used[0]:raise ValueError('transport-single-use')
        used[0]=True
        validate_transport(argv,timeout,input,expected_argv=expected_argv,expected_input_sha256=expected_input_sha256,minimum_seconds=minimum_seconds)
        return transfer.receive_command(argv,input=input,root=R,timeout=timeout,prefix=prefix)
    manager.command=adapter
    return manager
def _new_status_prefix():
    while True:
        prefix='status-'+os.urandom(8).hex()
        if not any((R/'evidence'/(prefix+s)).exists() for s in ('-status.json','-transfer.json','-wire-header.bin','-original-evidence.zip','-transport.stderr')):
            return prefix
def _require_intent(expected):
    path=R/'evidence/VM-submission-intent.json'
    require(_regular(path),'run-intent-missing')
    intent=_read_json(path)
    require(intent.get('attempts')==1 and intent.get('noAutomaticReplay') is True,'intent-replay')
    require(intent.get('guestRoot')==expected.get('guestRoot'),'intent-root')
    require(intent.get('payloadSha256')==expected.get('payloadSha256'),'intent-payload')
    return intent
def _status_query(packet,expected,transfer):
    _require_intent(expected)
    prefix=_new_status_prefix()
    remote=_build_status_remote(packet,expected)
    manager=_manager(prefix,transfer,sha256(remote.encode()).hexdigest(),1)
    p=manager.ssh('/usr/bin/python3 -I -B -',input=remote,timeout=660,phase='native-check')
    require(p.returncode==0,'status-transport-exit')
    d=json.loads(p.stdout)
    require(isinstance(d,dict) and d.get('kind')=='guest-readonly-status','status-kind')
    require(d.get('guestRoot')==expected.get('guestRoot'),'status-guest-root')
    raw=(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+chr(10)).encode('utf-8')
    require(len(raw)<=CAP-STOP_RESERVE,'status-log-cap')
    record(prefix+'-status.json',d)
    return d
def _action():
    args=sys.argv[1:]
    if not args or args==['run']:return 'run'
    if args==['status']:return 'status'
    raise ValueError('usage')
def main():
    require(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'),'optimized-host-forbidden')
    action=_action()
    packet=_read_json(R/'payload.json')
    expected=_read_json(R/'evidence/payload-manifest.json')
    validate_payload(packet,expected,R)
    admission=_admission(packet,expected)
    transfer=load('reviewed_transfer',R/'operator/transfer.py')
    if action=='status':
        try:
            d=_status_query(packet,expected,transfer)
            print(json.dumps(d))
            return 0 if isinstance(d,dict) and d.get('idleConfirmed') is True else 3
        except Exception as error:
            d={'kind':'VM-readonly-status-rejected','idleConfirmed':False,'transportReturned':False,'errorType':type(error).__name__,'reason':str(error)[:400],'formalTargets':'0/16','r3':'blocked'}
            print(json.dumps(d))
            return 3
    remote,code=_build_run_remote(packet)
    intent={'kind':'VM-submission-intent','remoteScriptSha256':sha256(remote.encode()).hexdigest(),'controllerSha256':sha256(code).hexdigest(),'payloadSha256':expected.get('payloadSha256'),'reviewReceiptSha256':admission.get('reviewReceiptSha256'),'guestRoot':packet.get('guestRoot'),'attempts':1,'noAutomaticReplay':True,'formalTargets':'0/16','r3':'blocked'}
    try:
        record('VM-submission-intent.json',intent)
    except Exception as error:
        d={'kind':'VM-full20-acceptance-rejected','allPassed':False,'transportReturned':False,'errorType':type(error).__name__,'reason':str(error)[:400],'formalTargets':'0/16','r3':'blocked'}
        print(json.dumps(d));return 3
    ssh_attempted=False
    transport_returned=False
    decision=None
    failure=None
    try:
        manager=_manager('VM',transfer,sha256(remote.encode()).hexdigest(),2700+120)
        ssh_attempted=True
        p=manager.ssh('/usr/bin/python3 -I -B -',input=remote,timeout=3000,phase='native-check')
        transport_returned=True
        require(p.returncode==0,'transport-exit')
        d=json.loads(p.stdout)
        record('VM-delivery.json',d)
        raw=(R/'evidence/VM-original-evidence.zip').read_bytes()
        verifier=load('independent_consumer_gate',R/'operator/verify_delivery.py')
        decision=verifier.verify_bundle(d,raw,expected)
        record('VM-acceptance.json',decision)
    except Exception as error:
        failure=error
        d={'kind':'VM-full20-acceptance-rejected','allPassed':False,'sshAttempted':ssh_attempted,'transportReturned':transport_returned,'errorType':type(error).__name__,'reason':str(error)[:400],'originalAttemptRetained':True,'noAutomaticReplay':True,'formalTargets':'0/16','r3':'blocked'}
        try:record('VM-acceptance.json',d,stop=True)
        except Exception:pass
        decision=d
    status=None
    if ssh_attempted:
        try:
            status=_status_query(packet,expected,transfer)
        except Exception as error:
            status={'kind':'VM-readonly-status-unknown','idleConfirmed':False,'errorType':type(error).__name__,'reason':str(error)[:400],'formalTargets':'0/16','r3':'blocked'}
    run_ok=bool(failure is None and isinstance(decision,dict) and decision.get('allPassed') is True)
    status_ok=bool(isinstance(status,dict) and status.get('idleConfirmed') is True and status.get('kind')=='guest-readonly-status' and status.get('guestRoot')==expected.get('guestRoot'))
    summary={k:v for k,v in (decision or {}).items() if k!='innerIdentityRecords'}
    print(json.dumps({'acceptance':summary,'status':status}))
    return 0 if run_ok and status_ok else 3
if __name__=='__main__':raise SystemExit(main())
