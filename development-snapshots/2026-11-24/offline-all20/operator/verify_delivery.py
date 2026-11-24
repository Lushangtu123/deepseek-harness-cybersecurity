"""Independent host byte/contract verification; no execution from a delivery."""
from pathlib import PurePosixPath
from hashlib import sha256
import io,json,stat,zipfile
CAP=67108864
def require(v,reason):
    if not v:raise ValueError(reason)
def verify_bundle(delivery,raw,expected):
    if expected.get('full20') is True:
        return verify_full20_bundle(delivery,raw,expected)
    require(type(delivery) is dict and type(raw) is bytes,'delivery-type')
    require(delivery.get('archiveComplete') is True and delivery.get('controllerFinalWritten') is True and delivery.get('collectionIssues')==[],'delivery-incomplete')
    require(len(raw)<=CAP and sha256(raw).hexdigest()==delivery.get('archiveSha256'),'archive-digest')
    require(delivery.get('guestRoot')==expected['guestRoot'],'guest-root')
    final=delivery.get('result');require(type(final) is dict,'final-shape')
    for flag in ['complete','suitePassed','targetChecksAllTrue','outerGroupExited','innerCleanupConfirmed','sourceUnchanged','budgetOk','unexpectedResourceCallLogEmpty']:require(final.get(flag) is True,'final:'+flag)
    require(final.get('sourceManifestSha256')==expected['sourceManifestSha256'],'final-source')
    frozen={n:v['sha256'] for n,v in expected['files'].items()};members=delivery.get('members');require(type(members) is dict,'member-map')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist();require(len(names)==len(set(names)),'duplicate-member')
        require(set(names)==set(members)|{'LINKS.json','ARCHIVE-ISSUES.json'},'member-set')
        require(sum(x.file_size for x in z.infolist())<=CAP,'uncompressed-cap')
        for n in names:
            p=PurePosixPath(n);require(not p.is_absolute() and str(p)==n and all(s not in ('','.','..') for s in n.split('/')),'archive-path')
            require(not stat.S_ISLNK(z.getinfo(n).external_attr>>16),'archive-link')
        require(z.testzip() is None,'archive-crc')
        for n,row in members.items():
            b=z.read(n);require(type(row) is dict and len(b)==row['bytes'] and sha256(b).hexdigest()==row['sha256'],'member:'+n)
        require(json.loads(z.read('LINKS.json'))==delivery['linksRecordedNotFollowed'] and json.loads(z.read('ARCHIVE-ISSUES.json'))==[],'collection-map')
        for n,row in expected['files'].items():
            b=z.read(n);require(len(b)==row['bytes'] and sha256(b).hexdigest()==row['sha256'],'input:'+n)
        require(json.loads(z.read('final.json'))==final,'outer-final')
        staged=json.loads(z.read('staging-verified.json'));require(staged['files']==frozen,'staged-inputs')
        result=json.loads(z.read('evidence/consumer-12/results.json'));rows=result.get('results')
        require(type(rows) is list and len(rows)==12 and all(type(x) is dict for x in rows),'rows')
        require([x.get('id') for x in rows]==expected['caseIds'],'case-ids')
        require(all(x.get('passed') is True for x in rows),'case-failed')
        require(type(result.get('passed')) is int and type(result.get('total')) is int and result['passed']==result['total']==12 and result.get('failed')==[],'counts')
        checks=rows[-1].get('detail',{}).get('checks');want={'exit3','noTraceback','diagnostic','noNewPlan','counterUnchanged','damagedBytesRetained'}
        require(type(checks) is dict and set(checks)==want and all(v is True for v in checks.values()),'target-assertion')
        require(rows[-1]['detail'].get('returncode')==3,'target-exit')
        capture=json.loads(z.read('evidence/consumer-12/capture.json'))
        require(capture.get('passed') is True and capture.get('returncode')==0 and capture.get('problem') is None and capture.get('cleanupConfirmed') is True,'outer-capture')
        require(capture['sourceAndScriptsBefore']==capture['sourceAndScriptsAfter']==frozen,'capture-inputs')
        require(capture['validationPassed']==capture['validationTotal']==12,'capture-validation')
        require(type(capture.get('capacitySamples')) is int and capture['capacitySamples']>0 and capture['peakTreeBytes']<=CAP-4194304 and capture['minFreeBytes']>=536870912,'capacity')
        run=json.loads(z.read('evidence/raw-consumer/run.json'))
        require(run.get('returncode')==0 and run.get('sourceUnchanged') is True and run.get('resultPassed')==run.get('resultTotal')==12,'raw-run')
        require(run['sourceManifestBefore']==run['sourceManifestAfter'] and run['sourceManifestBefore']['manifestSha256']==expected['sourceManifestSha256'],'raw-source')
        require(sha256(z.read('evidence/consumer-12/results.json')).hexdigest()==run['resultSha256'],'raw-result')
        for stream in ['stdout','stderr']:require(sha256(z.read('evidence/raw-consumer/'+stream+'.bin')).hexdigest()==run[stream+'Sha256'],'raw-'+stream)
        retained=result.get('retainedSandboxes');require(type(retained) is list and len(retained)==1 and retained[0].get('caseId')==expected['caseIds'][-1],'retained-map')
        box=retained[0]['relativePath'];require(box==final['inner']['box'] and box.startswith('checks/tmp/closure-public-compile-'),'retained-box')
        receipt_name=final['inner']['receipt'];require(receipt_name.startswith('candidate/'+box+'/preflight/evidence/'),'inner-receipt-path')
        receipt=json.loads(z.read(receipt_name));prefix=receipt_name.rsplit('/',1)[0]+'/'
        require(receipt['preflightId']==prefix.split('/')[-2] and receipt['cleanup']['confirmed'] is True,'inner-receipt')
        for n,h in receipt['evidenceDigests'].items():
            p=PurePosixPath(n);require(not p.is_absolute() and '..' not in p.parts,'inner-journal-path')
            require(sha256(z.read(prefix+n)).hexdigest()==h,'inner-journal:'+n)
        cleanup=json.loads(z.read(prefix+'cleanup.json'));require(cleanup['preflightId']==receipt['preflightId'] and cleanup['cleanup']['confirmed'] is True,'inner-cleanup')
        require(cleanup['cleanup']['stage']['removed'] is True and cleanup['cleanup']['stage']['lstatAfter']=='absent','stage-cleanup')
        identities={}
        for role in ['client','observer']:
            j=json.loads(z.read(prefix+'process-'+role+'-identity.json'));require(j['preflightId']==receipt['preflightId'] and j['role']==role and j['spawnState']=='started' and type(j.get('identity')) is dict,'identity:'+role);identities[role]=j
        require(z.read('evidence/unexpected-resource-calls.log')==b'','unexpected-resource-call')
    return {'kind':'independent-host-consumer12-acceptance','allPassed':True,'cases':12,'exactCaseIds':True,'allFrozenInputsMatch':True,'archiveMembers':len(names),'allMembersReadBack':True,'innerIdentityRecords':identities,'innerReceipt':receipt_name,'innerCurrentProcessQueriesRequired':True,'candidateManifestSha256':expected['sourceManifestSha256'],'notFull20Seal':True,'formalTargets':'0/16','r3':'blocked'}

def _f20_expected_rel(frozen,basename):
    mapping={'full20_batch.py':'operator/full20_batch.py','suite-plan.json':'operator/suite-plan.json','finalize_closure.py':'candidate/checks/finalize_closure.py'}
    require(basename in mapping,'full20:expected-name:'+basename)
    name=mapping[basename]
    require(name in frozen,'full20:expected-frozen:'+name)
    return name

def _f20_required_frozen(frozen):
    for name in ('operator/full20_batch.py','operator/suite-plan.json','candidate/checks/finalize_closure.py'):
        require(name in frozen,'full20:expected-frozen:'+name)

def _f20_host_root(expected=None):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent

def _f20_frozen(expected):
    files=expected.get('files')
    require(type(files) is dict and bool(files),'full20:expected-files')
    out={}
    for name,row in files.items():
        require(type(name) is str and name,'full20:expected-path')
        p=PurePosixPath(name)
        require(not p.is_absolute() and str(p)==name and all(s not in ('','.','..') for s in name.split('/')),'full20:expected-path:'+name)
        require(type(row) is dict and type(row.get('sha256')) is str and type(row.get('bytes')) is int and row['bytes']>=0,'full20:expected-row:'+name)
        out[name]={'sha256':row['sha256'],'bytes':row['bytes']}
    return out

def _f20_json_bytes(body,label):
    try:
        return json.loads(body.decode('utf-8'))
    except (ValueError,UnicodeDecodeError) as error:
        raise ValueError('full20:json:'+label+':'+type(error).__name__)

def _f20_blob(blobs,name,label):
    require(name in blobs,'full20:missing:'+label+':'+name)
    return blobs[name]

def _f20_json_blob(blobs,name,label):
    return _f20_json_bytes(_f20_blob(blobs,name,label),label)

def _f20_validate_archive(z,delivery,expected,members,frozen):
    names=z.namelist()
    require(len(names)==len(set(names)),'full20:duplicate-member')
    require(set(names)==set(members)|{'LINKS.json','ARCHIVE-ISSUES.json'},'full20:member-set')
    infos=z.infolist()
    require(sum(int(x.file_size) for x in infos)<=CAP,'full20:uncompressed-cap')
    for info in infos:
        name=info.filename
        p=PurePosixPath(name)
        require(not p.is_absolute() and str(p)==name and all(s not in ('','.','..') for s in name.split('/')),'full20:archive-path:'+name)
        require((info.flag_bits & 1)==0,'full20:encrypted:'+name)
        require(not info.is_dir(),'full20:directory-member:'+name)
        mode=info.external_attr>>16
        file_type=stat.S_IFMT(mode)
        require(file_type!=stat.S_IFLNK,'full20:archive-link:'+name)
        require(file_type in (0,stat.S_IFREG),'full20:special-member:'+name)
    require(z.testzip() is None,'full20:archive-crc')
    blobs={}
    for info in infos:
        blobs[info.filename]=z.read(info.filename)
    for name,row in members.items():
        require(type(name) is str and type(row) is dict,'full20:member-row:'+name)
        require(type(row.get('bytes')) is int and type(row.get('sha256')) is str,'full20:member-row:'+name)
        body=_f20_blob(blobs,name,'member')
        require(len(body)==row['bytes'] and sha256(body).hexdigest()==row['sha256'],'full20:member:'+name)
    require(json.loads(_f20_blob(blobs,'LINKS.json','links'))==delivery.get('linksRecordedNotFollowed'),'full20:collection-map')
    require(json.loads(_f20_blob(blobs,'ARCHIVE-ISSUES.json','issues'))==[],'full20:archive-issues')
    for name,row in frozen.items():
        body=_f20_blob(blobs,name,'input')
        require(len(body)==row['bytes'] and sha256(body).hexdigest()==row['sha256'],'full20:input:'+name)
    staged=_f20_json_blob(blobs,'staging-verified.json','staging')
    require(staged.get('files')=={n:v['sha256'] for n,v in frozen.items()},'full20:staged-inputs')
    return names,blobs

def _f20_load_host_module(frozen,host_root,basename):
    import sys,types
    from pathlib import Path
    rel=_f20_expected_rel(frozen,basename)
    path=Path(host_root)/rel
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError('not-regular')
        body=path.read_bytes()
    except OSError as error:
        raise ValueError('full20:host-read:'+basename+':'+type(error).__name__)
    row=frozen[rel]
    require(len(body)==row['bytes'] and sha256(body).hexdigest()==row['sha256'],'full20:host-digest:'+basename)
    module=types.ModuleType('_full20_host_'+basename.replace('.','_').replace('-','_'))
    module.__file__=str(path)
    old=sys.dont_write_bytecode
    sys.dont_write_bytecode=True
    try:
        code=compile(body,str(path),'exec')
        exec(code,module.__dict__)
    except BaseException as error:
        raise ValueError('full20:host-compile:'+basename+':'+type(error).__name__)
    finally:
        sys.dont_write_bytecode=old
    return module,rel

def _f20_source(module,host_root,expected,frozen,plan_sha):
    fn=getattr(module,'_source_state',None)
    require(callable(fn),'full20:host-source-validator-missing')
    candidate=host_root/'candidate'
    try:
        source=fn(candidate)
    except Exception as error:
        raise ValueError('full20:host-source:'+type(error).__name__+':'+str(error))
    require(type(source) is dict and type(source.get('files')) is dict and type(source.get('actual')) is dict and type(source.get('manifestSha256')) is str,'full20:host-source-shape')
    require(source['actual']==source['files'],'full20:host-source-actual')
    require(source['manifestSha256']==plan_sha,'full20:host-source-plan')
    require(source['manifestSha256']==expected.get('sourceManifestSha256'),'full20:host-source-expected')
    require(len(source['files'])==92,'full20:host-source-count')
    cand={k[len('candidate/'):]:v['sha256'] for k,v in frozen.items() if k.startswith('candidate/')}
    for rel,digest in source['files'].items():
        require(cand.get(rel)==digest,'full20:host-source-file:'+rel)
    manifest_rel='candidate/protocol-manifest.json'
    require(manifest_rel in frozen and frozen[manifest_rel]['sha256']==source['manifestSha256'],'full20:host-source-manifest')
    baseline_rel='candidate/baseline/protocol-manifest.json'
    baseline_sha=getattr(module,'_BASELINE_MANIFEST_SHA256',None)
    require(type(baseline_sha) is str and baseline_sha,'full20:host-baseline-digest-missing')
    require(baseline_rel in frozen and frozen[baseline_rel]['sha256']==baseline_sha,'full20:host-baseline-manifest')
    validator=getattr(module,'_validate_baseline_members',None)
    require(callable(validator),'full20:host-baseline-validator-missing')
    try:
        checked=validator(candidate)
    except Exception as error:
        raise ValueError('full20:host-baseline:'+type(error).__name__+':'+str(error))
    require(checked is True,'full20:host-baseline')
    return source

def _f20_registry(plan,expected,batch):
    require(type(plan) is dict,'full20:suite-plan-shape')
    order=plan.get('order')
    suites=plan.get('suites')
    require(type(order) is list and len(order)==20 and len(set(order))==20 and all(type(s) is str and s for s in order),'full20:suite-order')
    require(type(suites) is dict and set(suites)==set(order),'full20:suite-set')
    names=set()
    for suite in order:
        row=suites[suite]
        require(type(row) is dict,'full20:suite-row:'+suite)
        command=row.get('command')
        result=row.get('resultName')
        require(type(command) is list and command and all(type(x) is str and x for x in command),'full20:suite-command:'+suite)
        require(type(result) is str and result and PurePosixPath(result).name==result and result not in ('.','..'),'full20:result-name:'+suite)
        require(result not in names,'full20:result-name-duplicate:'+suite)
        names.add(result)
    sha=plan.get('sourceManifestSha256')
    require(type(sha) is str and sha==expected.get('sourceManifestSha256'),'full20:plan-source')
    validator=getattr(batch,'validate_registry',None)
    require(callable(validator),'full20:host-registry-validator-missing')
    checked=validator(plan,expected['sourceManifestSha256'])
    require(checked is True,'full20:registry')
    return order,suites,sha

def _f20_expand_command(tokens,expected,base_zip):
    root=expected['guestRoot'].rstrip('/')
    repl={'{PYTHON}':'/usr/bin/python3','{CANDIDATE}':root+'/candidate','{RUN}':root+'/'+base_zip,'{OPERATOR}':root+'/operator','{AUX}':root+'/checks/independent','{REFERENCES}':root+'/references'}
    out=[]
    for token in tokens:
        require(type(token) is str,'full20:command-token')
        value=token
        for key,replacement in repl.items():
            value=value.replace(key,replacement)
        require('{' not in value and '}' not in value,'full20:command-placeholder:'+token)
        out.append(value)
    require(out and out[0]=='/usr/bin/python3','full20:command-python')
    return out

def _f20_name(value,label):
    if type(value) is str:
        return value
    if type(value) is dict:
        for key in ('suite','id','name'):
            if type(value.get(key)) is str:
                return value[key]
    raise ValueError(label)

def _f20_named_list(final,key,order,label):
    value=final.get(key)
    require(type(value) is list and len(value)==20,label)
    names=[_f20_name(x,label) for x in value]
    require(names==order,label+':order')
    return value

def _f20_captures(final,order):
    value=final.get('captures')
    out={}
    if type(value) is dict:
        require(set(value)==set(order),'full20:captures')
        for suite in order:
            out[suite]=value[suite]
    elif type(value) is list:
        require(len(value)==20,'full20:captures')
        if all(type(x) is str for x in value):
            for suite,item in zip(order,value):
                out[suite]=item
        else:
            for item in value:
                suite=_f20_name(item,'full20:captures')
                require(suite in order and suite not in out,'full20:captures')
                if type(item) is dict:
                    path=None
                    for key in ('capture','path','capturePath'):
                        if type(item.get(key)) is str:
                            path=item[key]
                            break
                    require(path is not None,'full20:captures')
                    out[suite]=path
                else:
                    raise ValueError('full20:captures')
    else:
        raise ValueError('full20:captures')
    require(set(out)==set(order),'full20:captures')
    for suite in order:
        require(type(out[suite]) is str and out[suite].startswith('/'),'full20:capture-path:'+suite)
    return out

def _f20_capacity(row,suite):
    samples=row.get('capacitySamples')
    require(type(samples) is int and samples>0,'full20:capacity-samples:'+suite)
    peak=row.get('peakTreeBytes')
    free=row.get('minFreeBytes')
    require(type(peak) is int and peak>=0 and peak<=62914560,'full20:peak:'+suite)
    require(type(free) is int and free>=536870912,'full20:min-free:'+suite)

def _f20_no_stop(value,label):
    if type(value) is dict:
        for key in ('stopped','historical','partial','incomplete'):
            require(value.get(key) is not True,label+':'+key)
        status=value.get('status')
        if type(status) is str:
            require(status not in ('stopped','historical','partial','incomplete'),label+':status')

def _f20_snapshot_ok(value,source):
    if type(value) is not dict:
        return False
    return (value.get('ok') is True
            and value.get('manifestSha256')==source['manifestSha256']
            and value.get('entries')==source['actual']
            and value.get('problems')==[]
            and value.get('fileCount')==value.get('declaredCount')==92)

def _f20_final(final,expected,order,suites,commands,source,blobs,base_zip,frozen=None):
    require(type(final) is dict,'full20:final-shape')
    require(final.get('full20') is True and final.get('expectedGroups')==20,'full20:final-full20')
    require(final.get('batchState')=='pending-final-review','full20:final-state')
    require(final.get('complete') is True,'full20:final-complete')
    require(final.get('failedGroup') is None,'full20:final-failed-group')
    for flag in ('suitePassed','targetChecksAllTrue','outerGroupExited','innerCleanupConfirmed','sourceUnchanged','budgetOk','unexpectedResourceCallLogEmpty','actualProcessQuiescent'):
        require(final.get(flag) is True,'full20:final:'+flag)
    require(final.get('sourceManifestSha256')==source['manifestSha256'],'full20:final-source')
    _f20_no_stop(final,'full20:final')
    rows=_f20_named_list(final,'rows',order,'full20:rows')
    groups=_f20_named_list(final,'groups',order,'full20:groups')
    attempted=final.get('attemptedSuites')
    require(type(attempted) is list and len(attempted)==20,'full20:attempted')
    attempted_names=[_f20_name(x,'full20:attempted') for x in attempted]
    require(attempted_names==order,'full20:attempted:order')
    capmap=_f20_captures(final,order)
    root=expected['guestRoot'].rstrip('/')
    for suite in order:
        require(capmap[suite]==root+'/'+base_zip+'/raw/'+suite+'/run.json','full20:capture-guest:'+suite)
    frozen_map=None
    if frozen is not None:
        frozen_map={n:v['sha256'] for n,v in frozen.items()}
    for index,suite in enumerate(order):
        row=rows[index]
        require(type(row) is dict and _f20_name(row,'full20:row')==suite,'full20:row-suite:'+suite)
        require(row.get('passed') is True,'full20:row-passed:'+suite)
        require(row.get('cleanupConfirmed') is True,'full20:row-cleanup:'+suite)
        require(row.get('returncode')==0,'full20:row-returncode:'+suite)
        require(row.get('immutableFilesUnchanged') is True,'full20:row-immutable:'+suite)
        if frozen_map is not None:
            require(row.get('sourceAndScriptsBefore')==frozen_map,'full20:row-source-before:'+suite)
            require(row.get('sourceAndScriptsAfter')==frozen_map,'full20:row-source-after:'+suite)
        _f20_capacity(row,suite)
        _f20_no_stop(row,'full20:row:'+suite)
        group=groups[index]
        require(type(group) is dict and _f20_name(group,'full20:group')==suite,'full20:group-suite:'+suite)
        require(group.get('command')==commands[suite],'full20:group-command:'+suite)
        require(group.get('capture')==capmap[suite],'full20:group-capture:'+suite)
        require(group.get('sourceBefore')==source['manifestSha256'],'full20:group-source-before:'+suite)
        require(group.get('sourceAfter')==source['manifestSha256'],'full20:group-source-after:'+suite)
    return rows,groups,capmap

def _f20_field(doc,names):
    for name in names:
        if name in doc:
            return doc[name]
    return None

def _f20_raw(blobs,suite,result_name,command,source,expected,validator,host_root,base_zip):
    raw_zip=base_zip+'/raw/'+suite+'/run.json'
    cap=_f20_json_blob(blobs,raw_zip,'raw:'+suite)
    require(type(cap) is dict,'full20:raw-shape:'+suite)
    require(cap.get('suite')==suite,'full20:raw-suite:'+suite)
    require(cap.get('command')==command,'full20:raw-command:'+suite)
    require(cap.get('returncode')==0,'full20:raw-returncode:'+suite)
    require(cap.get('sourceClosureOk') is True,'full20:raw-source-closure:'+suite)
    require(cap.get('sourceUnchanged') is True,'full20:raw-source-unchanged:'+suite)
    for key in ('sourceManifestBefore','sourceManifestAfter'):
        require(_f20_snapshot_ok(cap.get(key),source),'full20:raw-'+key+':'+suite)
    require(cap.get('sourceManifestBefore')==cap.get('sourceManifestAfter'),'full20:raw-source-stable:'+suite)
    result_zip=base_zip+'/'+result_name
    root=expected['guestRoot'].rstrip('/')
    result_guest=root+'/'+base_zip+'/'+result_name
    require(cap.get('resultFile')==result_guest,'full20:raw-result-file:'+suite)
    result_body=_f20_blob(blobs,result_zip,'result:'+suite)
    result_sha=sha256(result_body).hexdigest()
    require(cap.get('resultSha256')==result_sha,'full20:raw-result-sha:'+suite)
    raw_dir=base_zip+'/raw/'+suite
    for side in ('stdout','stderr'):
        require(cap.get(side+'File')==side+'.bin','full20:raw-'+side+'-file:'+suite)
        body=_f20_blob(blobs,raw_dir+'/'+side+'.bin','raw:'+side+':'+suite)
        require(cap.get(side+'Sha256')==sha256(body).hexdigest(),'full20:raw-'+side+'-sha:'+suite)
        size=cap.get(side+'Bytes')
        require(type(size) is int and size==len(body),'full20:raw-'+side+'-bytes:'+suite)
    rc_body=_f20_blob(blobs,raw_dir+'/returncode.txt','raw:returncode:'+suite)
    require(rc_body==b'0'+bytes([10]),'full20:raw-returncode-file:'+suite)
    require('returncodeFile' not in cap,'full20:raw-returncode-name:'+suite)
    for stem,key in (('source-before.json','sourceManifestBefore'),('source-after.json','sourceManifestAfter')):
        name=raw_dir+'/'+stem
        if name in blobs:
            require(_f20_json_blob(blobs,name,'raw:'+stem+':'+suite)==cap.get(key),'full20:raw-'+stem+':'+suite)
    result=_f20_json_bytes(result_body,'result:'+suite)
    require(type(result) is dict,'full20:result-shape:'+suite)
    if suite=='baseline-verify':
        passed,total=validator._validate_baseline_entry(result,str(host_root/'candidate'))
    elif suite=='independent-116':
        passed,total=validator._validate_independent_entry(result,suite,source)
    else:
        passed,total=validator._validate_ordinary_entry(result,suite,source,'offline-closure')
    require(type(passed) is int and type(total) is int and passed==total,'full20:validator-count:'+suite)
    rp=cap.get('resultPassed')
    rt=cap.get('resultTotal')
    if suite=='baseline-verify':
        require(rp is None and rt is None,'full20:raw-result-count:'+suite)
    else:
        require(type(rp) is int and type(rt) is int and rp==passed and rt==total,'full20:raw-result-count:'+suite)
    return cap,result,raw_zip,result_zip,result_guest,passed,total

def _f20_wrapper_command_ok(command,producer,expected_command=None):
    require(type(command) is list and command,'full20:wrapper-command')
    require(len(command)>=9 and command[0]=='/usr/bin/python3' and command[1]=='-I' and command[2]=='-B','full20:wrapper-python')
    require(PurePosixPath(command[3]).name=='evidence_capture.py','full20:wrapper-evidence-capture')
    require(type(producer) is list and producer,'full20:wrapper-producer')
    require(len(command)>len(producer) and command[-len(producer):]==producer,'full20:wrapper-producer')
    sep=len(command)-len(producer)-1
    require(sep>=4 and command[sep]=='--','full20:wrapper-separator')
    if expected_command is None:
        require(command[4]=='--suite' and type(command[5]) is str and command[5],'full20:wrapper-suite')
        suite=command[5]
        require('--out' in producer,'full20:wrapper-result')
        out_index=producer.index('--out')
        require(out_index+1<len(producer) and type(producer[out_index+1]) is str and producer[out_index+1],'full20:wrapper-result')
        result=producer[out_index+1]
        suffix='/checks/evidence-runs/full20-linux-20261123/'+PurePosixPath(result).name
        require(result.endswith(suffix),'full20:wrapper-result')
        candidate=result[:-len(suffix)]
        require(candidate and PurePosixPath(candidate).name=='candidate','full20:wrapper-candidate')
        run_dir=candidate+'/checks/evidence-runs/full20-linux-20261123/raw/'+suite
        expected_command=['/usr/bin/python3','-I','-B',candidate+'/checks/evidence_capture.py','--suite',suite,'--source-root',candidate,'--run-dir',run_dir,'--result',result,'--timeout','100','--',*producer]
    require(command==expected_command,'full20:wrapper-command')

def _f20_wrapper(blobs,suite,producer_command,candidate_guest,row=None,expected_command=None,frozen=None):
    base='evidence/'+suite
    intent=_f20_json_blob(blobs,base+'/intent.json','wrapper-intent:'+suite)
    process=_f20_json_blob(blobs,base+'/process.json','wrapper-process:'+suite)
    capture=_f20_json_blob(blobs,base+'/capture.json','wrapper-capture:'+suite)
    out=_f20_blob(blobs,base+'/stdout.bin','wrapper-stdout:'+suite)
    err=_f20_blob(blobs,base+'/stderr.bin','wrapper-stderr:'+suite)
    require(type(intent) is dict,'full20:wrapper-intent-shape:'+suite)
    require(type(process) is dict,'full20:wrapper-process-shape:'+suite)
    require(type(capture) is dict,'full20:wrapper-capture-shape:'+suite)
    if row is not None:
        require(capture==row,'full20:wrapper-capture-row:'+suite)
    require(intent.get('suite')==suite,'full20:wrapper-suite:'+suite)
    require(intent.get('cwd')==candidate_guest,'full20:wrapper-cwd:'+suite)
    require(intent.get('identityRequired') is True,'full20:wrapper-identity-required:'+suite)
    require(intent.get('createdBeforeProcess') is True,'full20:wrapper-created-before:'+suite)
    command=intent.get('command')
    require(type(command) is list and command,'full20:wrapper-command:'+suite)
    _f20_wrapper_command_ok(command,producer_command,expected_command)
    pid=process.get('pid')
    process_group=process.get('processGroup')
    require(type(pid) is int and pid>0 and process_group==pid,'full20:wrapper-process-pid:'+suite)
    require(capture.get('pid')==pid,'full20:wrapper-capture-pid:'+suite)
    identity=process.get('identity')
    require(type(identity) is dict,'full20:wrapper-identity:'+suite)
    ipid=identity.get('pid')
    ipgid=identity.get('pgid')
    require(type(ipid) is int and type(ipgid) is int and ipid==pid and ipgid==process_group,'full20:wrapper-identity-pid:'+suite)
    require(identity.get('groupLeader') is True,'full20:wrapper-group-leader:'+suite)
    start=identity.get('starttime')
    require(type(start) is int and start>0,'full20:wrapper-starttime:'+suite)
    boot=identity.get('bootId')
    require(type(boot) is str and bool(boot),'full20:wrapper-boot-id:'+suite)
    counts=capture.get('outputBytes')
    require(type(counts) is dict,'full20:wrapper-output-bytes:'+suite)
    require(counts.get('stdout')==len(out) and counts.get('stderr')==len(err),'full20:wrapper-output-bytes:'+suite)
    return process,identity

def _f20_index(blobs,order,suites,base_zip,rawmap,source=None):
    name='candidate/checks-evidence-index.json'
    body=_f20_blob(blobs,name,'index')
    index=_f20_json_bytes(body,'index')
    require(type(index) is dict and index.get('kind')=='consumer-closure-evidence-index','full20:index-kind')
    require(index.get('state')=='completed','full20:index-state')
    entries=index.get('entries')
    require(type(entries) is list and len(entries)==20,'full20:index-entries')
    names=[_f20_name(x,'full20:index') for x in entries]
    require(names==order,'full20:index-order')
    sm=index.get('sourceManifest')
    require(type(sm) is dict,'full20:index-source-manifest')
    if source is not None:
        require(sm.get('sha256')==source['manifestSha256'],'full20:index-source-sha')
        require(sm.get('entries')==source['actual'],'full20:index-source-entries')
        require(sm.get('fileCount')==92,'full20:index-source-count')
    else:
        require(type(sm.get('entries')) is dict and len(sm.get('entries'))==92 and sm.get('fileCount')==92,'full20:index-source-manifest')
    index_base=base_zip[len('candidate/'):]
    for entry,suite in zip(entries,order):
        require(type(entry) is dict,'full20:index-entry:'+suite)
        require(set(entry)=={'suite','command','captureFile','captureSha256','resultFile','resultSha256'},'full20:index-entry-fields:'+suite)
        cap_rel=index_base+'/raw/'+suite+'/run.json'
        res_rel=index_base+'/'+suites[suite]['resultName']
        require(entry.get('suite')==suite,'full20:index-suite:'+suite)
        require(entry.get('captureFile')==cap_rel,'full20:index-capture-file:'+suite)
        require(entry.get('resultFile')==res_rel,'full20:index-result-file:'+suite)
        cap_body=_f20_blob(blobs,base_zip+'/raw/'+suite+'/run.json','index-capture:'+suite)
        res_body=_f20_blob(blobs,base_zip+'/'+suites[suite]['resultName'],'index-result:'+suite)
        require(entry.get('captureSha256')==sha256(cap_body).hexdigest(),'full20:index-capture-sha:'+suite)
        require(entry.get('resultSha256')==sha256(res_body).hexdigest(),'full20:index-result-sha:'+suite)
        require(entry.get('command')==rawmap[suite].get('command'),'full20:index-command:'+suite)
    return index,sha256(body).hexdigest()

def _f20_proof(blobs,expected,source,index_sha,passed=None,total=None):
    name='candidate/proof.json'
    body=_f20_blob(blobs,name,'proof')
    proof=_f20_json_bytes(body,'proof')
    require(type(proof) is dict,'full20:proof-shape')
    require(proof.get('kind')=='consumer-closure-proof','full20:proof-kind')
    require(proof.get('state')=='verified','full20:proof-state')
    require(proof.get('decision')=='pass','full20:proof-decision')
    require(proof.get('verdict')=='pass','full20:proof-verdict')
    require(proof.get('sourceRoot')==expected['guestRoot'].rstrip('/')+'/candidate','full20:proof-source-root')
    require(proof.get('sourceManifestSha256')==source['manifestSha256'],'full20:proof-source-sha')
    require(proof.get('evidenceIndexSha256')==index_sha,'full20:proof-index-sha')
    require(proof.get('entryCount')==20,'full20:proof-entry-count')
    if passed is None or total is None:
        require(type(proof.get('passed')) is int and type(proof.get('total')) is int and proof['passed']==proof['total'] and proof['passed']>0,'full20:proof-counts')
    else:
        require(type(passed) is int and type(total) is int and passed==total and proof.get('passed')==passed and proof.get('total')==total,'full20:proof-counts')
    require(proof.get('sourceFileCount')==len(source['actual']),'full20:proof-source-count')
    checks=proof.get('checks')
    require(type(checks) is dict and set(checks)=={'sourceManifest','evidenceIndex','rawMembers','derivedDecision'},'full20:proof-checks')
    require(checks.get('derivedDecision')=='pass','full20:proof-checks')
    for key in ('sourceManifest','evidenceIndex','rawMembers'):
        require(checks.get(key) is True,'full20:proof-check:'+key)
    require(proof.get('targetExecutions')==0 and proof.get('realContainers')==0 and proof.get('realBpftrace')==0,'full20:proof-executions')
    require(proof.get('formalTargets')=='0/16' and proof.get('r3')=='blocked','full20:proof-boundaries')
    return proof,sha256(body).hexdigest()

def _f20_closure(blobs,expected,source,order,suites,base_zip):
    name='candidate/closure-manifest.json'
    doc=_f20_json_blob(blobs,name,'closure')
    require(type(doc) is dict,'full20:closure-shape')
    require(doc.get('sourceRoot')==expected['guestRoot'].rstrip('/')+'/candidate','full20:closure-source-root')
    require(doc.get('sourceManifestSha256')==source['manifestSha256'],'full20:closure-source-sha')
    files=doc.get('files')
    require(type(files) is dict,'full20:closure-files')
    require(doc.get('fileCount')==len(files),'full20:closure-count')
    for rel,digest in files.items():
        require(type(rel) is str and type(digest) is str,'full20:closure-file:'+str(rel))
        p=PurePosixPath(rel)
        require(not p.is_absolute() and str(p)==rel and all(s not in ('','.','..') for s in rel.split('/')),'full20:closure-path:'+rel)
        body=_f20_blob(blobs,'candidate/'+rel,'closure-member:'+rel)
        require(sha256(body).hexdigest()==digest,'full20:closure-digest:'+rel)
    required=doc.get('requiredClosureMembers')
    require(type(required) is list,'full20:closure-required')
    req=set(required)
    for member in ('REPORT.md','phase-result.json','checks-evidence-index.json','proof.json'):
        require(member in req and member in files,'full20:closure-required:'+member)
    maps=doc.get('validatedArtifactMap')
    require(type(maps) is list and len(maps)==100,'full20:closure-artifacts')
    require(doc.get('validatedArtifactCount')==100,'full20:closure-artifact-count')
    roles={'capture':'capture.json','result':'result.json','stdout':'stdout.bin','stderr':'stderr.bin','returncode':'returncode.txt'}
    seen=set()
    seen_arch=set()
    index_base=base_zip[len('candidate/'):]
    expected_rel={}
    for suite in order:
        expected_rel[(suite,'capture')]=index_base+'/raw/'+suite+'/run.json'
        expected_rel[(suite,'result')]=index_base+'/'+suites[suite]['resultName']
        expected_rel[(suite,'stdout')]=index_base+'/raw/'+suite+'/stdout.bin'
        expected_rel[(suite,'stderr')]=index_base+'/raw/'+suite+'/stderr.bin'
        expected_rel[(suite,'returncode')]=index_base+'/raw/'+suite+'/returncode.txt'
    root=expected['guestRoot'].rstrip('/')+'/candidate'
    for rec in maps:
        require(type(rec) is dict,'full20:artifact-shape')
        suite=rec.get('suite')
        role=rec.get('role')
        require(suite in order and role in roles,'full20:artifact-suite')
        key=(suite,role)
        require(key not in seen,'full20:artifact-duplicate:'+str(key))
        seen.add(key)
        arch=rec.get('archivePath')
        require(type(arch) is str,'full20:artifact-archive')
        p=PurePosixPath(arch)
        require(not p.is_absolute() and str(p)==arch and all(s not in ('','.','..') for s in arch.split('/')),'full20:artifact-archive-path')
        require(arch not in seen_arch,'full20:artifact-archive-duplicate:'+arch)
        seen_arch.add(arch)
        require(arch=='evidence/'+suite+'/'+roles[role],'full20:artifact-archive-name:'+suite+':'+role)
        rel=rec.get('relativePath')
        require(type(rel) is str,'full20:artifact-relative')
        require(rel==expected_rel[(suite,role)],'full20:artifact-relative:'+suite+':'+role)
        source_path=rec.get('sourcePath')
        require(type(source_path) is str,'full20:artifact-source-path')
        require(source_path==root+'/'+rel,'full20:artifact-source-path:'+suite+':'+role)
        declared_bytes=rec.get('bytes')
        declared_sha=rec.get('sha256')
        require(type(declared_bytes) is int and declared_bytes>=0 and type(declared_sha) is str,'full20:artifact-fields')
        identity=rec.get('identity')
        require(type(identity) in (list,tuple) and len(identity)==2 and type(identity[0]) is int and type(identity[1]) is int,'full20:artifact-identity')
        orig=_f20_blob(blobs,'candidate/'+rel,'artifact-original:'+suite+':'+role)
        archived=_f20_blob(blobs,'candidate/'+arch,'artifact-archive:'+suite+':'+role)
        require(orig==archived and len(orig)==declared_bytes and sha256(orig).hexdigest()==declared_sha,'full20:artifact-bytes:'+suite+':'+role)
    require(seen==set(expected_rel),'full20:artifact-cover')
    return doc,sha256(_f20_blob(blobs,name,'closure')).hexdigest()

def _f20_phase(blobs,source=None,order=None):
    report=_f20_blob(blobs,'candidate/REPORT.md','report')
    require(len(report)>0,'full20:report-empty')
    phase=_f20_json_blob(blobs,'candidate/phase-result.json','phase')
    require(type(phase) is dict,'full20:phase-shape')
    require(phase.get('kind')=='full20-linux-regression-phase','full20:phase-kind')
    require(phase.get('version')==1,'full20:phase-version')
    require(phase.get('state')=='pending-independent-review','full20:phase-state')
    if source is not None:
        require(phase.get('sourceManifestSha256')==source['manifestSha256'],'full20:phase-source')
    require(phase.get('expectedGroups')==20,'full20:phase-expected-groups')
    require(phase.get('completedGroups')==20,'full20:phase-completed-groups')
    if order is not None:
        attempted=phase.get('attemptedSuites')
        require(type(attempted) is list and [_f20_name(x,'full20:phase-attempted') for x in attempted]==order,'full20:phase-attempted')
    require(phase.get('resourceQuiescent') is True,'full20:phase-resource')
    require(phase.get('sourceUnchanged') is True,'full20:phase-source-unchanged')
    require(phase.get('formalTargets')=='0/16' and phase.get('r3')=='blocked','full20:phase-boundaries')
    return phase

def _f20_pub_value(pub,names):
    for name in names:
        value=pub.get(name)
        if type(value) is str and value:
            return value
        if type(value) is dict:
            for key in ('sha256','digest','hash'):
                if type(value.get(key)) is str:
                    return value[key]
    return None

def _f20_publication(final,index_sha,proof_sha,closure_sha,expected,source,order,passed=None,total=None,report_sha=None):
    pub=final.get('publication')
    require(type(pub) is dict,'full20:publication')
    index=pub.get('index')
    proof=pub.get('proof')
    gate=pub.get('gate')
    require(type(index) is dict and index.get('ok') is True,'full20:publication-index')
    require(index.get('sha256')==index_sha and index.get('entries')==20,'full20:publication-index')
    require(type(proof) is dict and proof.get('ok') is True and proof.get('sha256')==proof_sha,'full20:publication-proof')
    require(type(gate) is dict,'full20:publication-gate')
    require(gate.get('state')=='pending-independent-review','full20:publication-gate-state')
    require(gate.get('archiveCalls')==0,'full20:publication-archive-calls')
    closure=gate.get('closureManifest')
    require(type(closure) is dict and closure.get('ok') is True and closure.get('sha256')==closure_sha,'full20:publication-closure')
    require(pub.get('operatorArchivePending') is True,'full20:publication-archive-pending')
    if report_sha is not None:
        report=gate.get('report')
        require(type(report) is dict and report.get('sha256')==report_sha,'full20:publication-report')
        gate_proof=gate.get('proof')
        require(type(gate_proof) is dict and gate_proof.get('ok') is True,'full20:publication-gate-proof')
        if 'proofSha256' in gate_proof:
            require(gate_proof.get('proofSha256')==proof_sha,'full20:publication-gate-proof-sha')
        if 'evidenceIndexSha256' in gate_proof:
            require(gate_proof.get('evidenceIndexSha256')==index_sha,'full20:publication-gate-index-sha')
        if 'sourceManifestSha256' in gate_proof:
            require(gate_proof.get('sourceManifestSha256')==source['manifestSha256'],'full20:publication-gate-source')
    if passed is not None and total is not None:
        gate_proof=gate.get('proof')
        if type(gate_proof) is dict:
            if 'passed' in gate_proof:
                require(gate_proof.get('passed')==passed,'full20:publication-gate-passed')
            if 'total' in gate_proof:
                require(gate_proof.get('total')==total,'full20:publication-gate-total')
    return pub

def _f20_consumer12(result,expected,final,blobs,base_zip):
    rows=result.get('results')
    require(type(rows) is list and len(rows)==12,'full20:consumer-rows')
    require([x.get('id') for x in rows]==expected.get('caseIds'),'full20:consumer-case-ids')
    last=rows[-1]
    detail=last.get('detail')
    require(type(detail) is dict,'full20:consumer-detail')
    checks=detail.get('checks')
    want={'exit3','noTraceback','diagnostic','noNewPlan','counterUnchanged','damagedBytesRetained'}
    require(type(checks) is dict and set(checks)==want and all(v is True for v in checks.values()),'full20:consumer-target-assertion')
    require(detail.get('returncode')==3,'full20:consumer-target-exit')
    retained=result.get('retainedSandboxes')
    require(type(retained) is list and len(retained)==1,'full20:consumer-retained')
    box=retained[0].get('relativePath')
    require(type(box) is str and box.startswith('checks/tmp/closure-public-compile-'),'full20:consumer-box')
    require(retained[0].get('caseId')==expected['caseIds'][-1],'full20:consumer-box-case')
    inner=final.get('inner')
    require(type(inner) is dict,'full20:consumer-inner')
    require(inner.get('box')==box,'full20:consumer-inner-box')
    receipt_name=inner.get('receipt')
    require(type(receipt_name) is str and receipt_name.startswith('candidate/'+box+'/preflight/evidence/'),'full20:consumer-receipt-path')
    receipt=_f20_json_blob(blobs,receipt_name,'consumer-receipt')
    prefix=receipt_name.rsplit('/',1)[0]+'/'
    require(receipt.get('preflightId')==prefix.split('/')[-2],'full20:consumer-preflight-id')
    require(type(receipt.get('cleanup')) is dict and receipt['cleanup'].get('confirmed') is True,'full20:consumer-receipt-cleanup')
    evidence=receipt.get('evidenceDigests')
    require(type(evidence) is dict and evidence,'full20:consumer-evidence')
    for rel,digest in evidence.items():
        p=PurePosixPath(rel)
        require(not p.is_absolute() and all(s not in ('','.','..') for s in rel.split('/')),'full20:consumer-journal-path')
        body=_f20_blob(blobs,prefix+rel,'consumer-journal:'+rel)
        require(sha256(body).hexdigest()==digest,'full20:consumer-journal:'+rel)
    cleanup=_f20_json_blob(blobs,prefix+'cleanup.json','consumer-cleanup')
    require(cleanup.get('preflightId')==receipt.get('preflightId'),'full20:consumer-cleanup-id')
    stage=cleanup.get('cleanup',{}).get('stage')
    require(type(stage) is dict and stage.get('removed') is True and stage.get('lstatAfter')=='absent','full20:consumer-stage-cleanup')
    for role in ('client','observer'):
        name='process-'+role+'-identity.json'
        require(name in evidence,'full20:consumer-identity-digest:'+role)
        doc=_f20_json_blob(blobs,prefix+name,'consumer-identity:'+role)
        require(doc.get('preflightId')==receipt.get('preflightId') and doc.get('role')==role and doc.get('spawnState')=='started' and type(doc.get('identity')) is dict,'full20:consumer-identity:'+role)
    return True

def verify_full20_bundle(delivery,raw,expected):
    require(type(delivery) is dict and type(raw) is bytes,'full20:delivery-type')
    require(type(expected) is dict and expected.get('full20') is True,'full20:expected')
    require(delivery.get('archiveComplete') is True and delivery.get('controllerFinalWritten') is True and delivery.get('collectionIssues')==[],'full20:delivery-incomplete')
    require(delivery.get('guestRoot')==expected.get('guestRoot'),'full20:guest-root')
    require(len(raw)<=CAP and sha256(raw).hexdigest()==delivery.get('archiveSha256'),'full20:archive-digest')
    frozen=_f20_frozen(expected)
    _f20_required_frozen(frozen)
    members=delivery.get('members')
    require(type(members) is dict,'full20:member-map')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names,blobs=_f20_validate_archive(z,delivery,expected,members,frozen)
    except zipfile.BadZipFile as error:
        raise ValueError('full20:archive-bad:'+type(error).__name__)
    final=_f20_json_blob(blobs,'final.json','final')
    require(final==delivery.get('result'),'full20:outer-final')
    plan=_f20_json_blob(blobs,'operator/suite-plan.json','suite-plan')
    host_root=_f20_host_root(expected)
    batch,_batch_rel=_f20_load_host_module(frozen,host_root,'full20_batch.py')
    finalize,_finalize_rel=_f20_load_host_module(frozen,host_root,'finalize_closure.py')
    order,suites,plan_sha=_f20_registry(plan,expected,batch)
    source=_f20_source(finalize,host_root,expected,frozen,plan_sha)
    base_zip='candidate/checks/evidence-runs/full20-linux-20261123'
    commands={}
    for suite in order:
        commands[suite]=_f20_expand_command(suites[suite]['command'],expected,base_zip)
    rows,groups,capmap=_f20_final(final,expected,order,suites,commands,source,blobs,base_zip,frozen)
    candidate_guest=expected['guestRoot'].rstrip('/')+'/candidate'
    run_root=candidate_guest+'/checks/evidence-runs/full20-linux-20261123'
    raw_caps={}
    results={}
    case_passed=0
    case_total=0
    for suite in order:
        cap,result,raw_zip,result_zip,result_guest,passed,total=_f20_raw(blobs,suite,suites[suite]['resultName'],commands[suite],source,expected,finalize,host_root,base_zip)
        raw_caps[suite]=cap
        results[suite]=result
        case_passed+=passed
        case_total+=total
        raw_dir=base_zip+'/raw/'+suite
        require(_f20_json_blob(blobs,raw_dir+'/source-before.json','raw-source-before:'+suite)==cap.get('sourceManifestBefore'),'full20:raw-source-before:'+suite)
        require(_f20_json_blob(blobs,raw_dir+'/source-after.json','raw-source-after:'+suite)==cap.get('sourceManifestAfter'),'full20:raw-source-after:'+suite)
        group=groups[order.index(suite)]
        require(group.get('captureSha256')==sha256(_f20_blob(blobs,raw_zip,'group-capture:'+suite)).hexdigest(),'full20:group-capture-sha:'+suite)
        require(group.get('validationCounts')==[passed,total],'full20:group-validation-counts:'+suite)
        expected_wrapper=['/usr/bin/python3','-I','-B',candidate_guest+'/checks/evidence_capture.py','--suite',suite,'--source-root',candidate_guest,'--run-dir',run_root+'/raw/'+suite,'--result',run_root+'/'+suites[suite]['resultName'],'--timeout','100','--',*commands[suite]]
        _f20_wrapper(blobs,suite,commands[suite],candidate_guest,row=rows[order.index(suite)],expected_command=expected_wrapper,frozen=frozen)
    require(case_passed==case_total,'full20:case-total')
    index,index_sha=_f20_index(blobs,order,suites,base_zip,raw_caps,source)
    proof,proof_sha=_f20_proof(blobs,expected,source,index_sha,case_passed,case_total)
    closure,closure_sha=_f20_closure(blobs,expected,source,order,suites,base_zip)
    phase=_f20_phase(blobs,source,order)
    report_sha=sha256(_f20_blob(blobs,'candidate/REPORT.md','report')).hexdigest()
    _f20_publication(final,index_sha,proof_sha,closure_sha,expected,source,order,case_passed,case_total,report_sha)
    require(_f20_blob(blobs,'evidence/unexpected-resource-calls.log','unexpected-resource-call')==b'','full20:unexpected-resource-call')
    _f20_consumer12(results['consumer-12'],expected,final,blobs,base_zip)
    return {'kind':'independent-host-full20-acceptance','allPassed':True,'suites':20,'exactSuiteOrder':True,'sourceManifestSha256':source['manifestSha256'],'archiveMembers':len(names),'archiveBytes':len(raw),'validatedArtifactCount':100,'formalTargets':'0/16','r3':'blocked','offlineTestClassification':True,'archivedProcessQuiescenceClaimOnly':True,'actualProcessStatusSeparateStep':True}
