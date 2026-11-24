'''Read-only full20 status; no writes, signals, or cleanup.'''
from pathlib import Path
import fcntl,hashlib,json,os,re,stat,sys,types
GUEST=Path('/home/purge/workspace/harness-new-script-acceptance-20261113/stdlib-cli-all20-fixture-lifecycle-20261124-r1')
RUN=GUEST/'candidate/checks/evidence-runs/full20-linux-20261123'
UID=1000
SANDBOX_RE=re.compile('checks/tmp/closure-public-compile-[0-9a-f]{8}')
PREFLIGHT_RE=re.compile('[0-9a-f]{32}')
FINAL_CASE_ID='public-compile-known-failure-is-diagnostic-3'
def _valid_rel(name):
    if not isinstance(name,str):return False
    p=Path(name)
    return not p.is_absolute() and str(p)==name and bool(p.parts) and '..' not in p.parts
def _regular(path):
    try:info=os.lstat(path)
    except OSError:return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
def _directory(path):
    try:info=os.lstat(path)
    except OSError:return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
def _absent(path):
    try:os.lstat(path)
    except FileNotFoundError:return True
    except OSError:return False
    return False
def _read_json(path):
    with open(path,'rb') as f:return json.loads(f.read())
def _root_check():
    try:info=os.lstat(GUEST)
    except FileNotFoundError:return False,'absent'
    except OSError:return False,'unknown'
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):return False,'not-directory'
    if info.st_uid!=UID:return False,'owner'
    cur=GUEST
    while cur!=cur.parent:
        cur=cur.parent
        try:info=os.lstat(cur)
        except OSError:return False,'ancestor'
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):return False,'ancestor'
    return True,None
def _no_symlink_components(base,rel):
    cur=Path(base)
    try:info=os.lstat(cur)
    except OSError:return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):return False
    for part in Path(rel).parts:
        cur=cur/part
        try:info=os.lstat(cur)
        except OSError:return False
        if stat.S_ISLNK(info.st_mode):return False
    return True
def _no_symlink_parents(base,path):
    cur=Path(base)
    if not _directory(cur):return False
    try:rel=path.parent.relative_to(cur)
    except ValueError:return False
    for part in rel.parts:
        cur=cur/part
        try:info=os.lstat(cur)
        except OSError:return False
        if stat.S_ISLNK(info.st_mode):return False
    return True
def _verify_expected(expected):
    if not isinstance(expected,dict):return False,['expected-object']
    files=expected.get('files')
    if not isinstance(files,dict) or not files:return False,['expected-files']
    for name,row in files.items():
        if not _valid_rel(name):return False,['expected-path:'+str(name)]
        if not isinstance(row,dict):return False,['expected-row:'+name]
        if not _no_symlink_components(GUEST,name):return False,['expected-symlink:'+name]
        path=GUEST/name
        if not _regular(path):return False,['expected-regular:'+name]
        try:raw=path.read_bytes()
        except OSError as e:return False,['expected-read:'+name+':'+type(e).__name__]
        if hashlib.sha256(raw).hexdigest()!=row.get('sha256'):return False,['expected-sha:'+name]
        size=row.get('bytes',row.get('size'))
        if not isinstance(size,int) or len(raw)!=size:return False,['expected-size:'+name]
    return True,[]
def _expected_raw(expected,name):
    if not isinstance(expected,dict):raise ValueError('expected-object')
    files=expected.get('files')
    if not isinstance(files,dict):raise ValueError('expected-files')
    row=files.get(name)
    if not isinstance(row,dict):raise ValueError('expected-entry:'+str(name))
    if not _valid_rel(name):raise ValueError('expected-path:'+str(name))
    if not _no_symlink_components(GUEST,name):raise ValueError('expected-symlink:'+str(name))
    path=GUEST/name
    if not _regular(path):raise ValueError('expected-regular:'+str(name))
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row.get('sha256'):raise ValueError('expected-sha:'+str(name))
    size=row.get('bytes',row.get('size'))
    if not isinstance(size,int) or len(raw)!=size:raise ValueError('expected-size:'+str(name))
    return raw
def _compile_verified_module(name,path,raw):
    mod=types.ModuleType(name)
    mod.__file__=str(path)
    exec(compile(raw,mod.__file__,'exec'),mod.__dict__)
    return mod
def _load_guard(raw=None):
    name='candidate/tools/resource_guard.py'
    if raw is None:raw=(GUEST/name).read_bytes()
    mod=types.ModuleType('resource_guard')
    mod.__file__=str(GUEST/name)
    exec(compile(raw,mod.__file__,'exec'),mod.__dict__)
    sys.modules['resource_guard']=mod
    return mod
def _state_exited(value):
    return isinstance(value,dict) and value.get('state')=='exited'
def _identity_relation(record,identity):
    if not isinstance(identity,dict):return False,'identity-missing'
    pid=record.get('pid');pgid=record.get('processGroup')
    if type(pid) is not int or pid<=0:return False,'top-level-pid'
    if type(pgid) is not int or pgid<=0:return False,'top-level-pgid'
    if pid!=pgid:return False,'top-level-group-mismatch'
    if record.get('originalPopenChild') is not True:return False,'not-original-child'
    if type(identity.get('pid')) is not int or identity['pid']!=pid:return False,'identity-pid'
    if type(identity.get('pgid')) is not int or identity['pgid']!=pgid:return False,'identity-pgid'
    if identity.get('groupLeader') is not True:return False,'identity-leader'
    if type(identity.get('starttime')) is not int or identity['starttime']<=0:return False,'identity-starttime'
    if not isinstance(identity.get('bootId'),str) or not identity['bootId']:return False,'identity-bootid'
    return True,None
def _batch_lock():
    path=GUEST/'.batch.lock'
    try:info=os.lstat(path)
    except FileNotFoundError:return {'state':'missing','released':False}
    except OSError as e:return {'state':'unknown','released':False,'reason':type(e).__name__}
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=UID:
        return {'state':'unknown','released':False}
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    except OSError as e:return {'state':'unknown','released':False,'reason':type(e).__name__}
    try:
        try:fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB);released=True
        except BlockingIOError:released=False
    finally:os.close(fd)
    return {'state':'released' if released else 'locked','released':released}
def _outer_groups(guard):
    final_path=GUEST/'final.json'
    if not _regular(final_path):
        return {'state':'unknown','reason':'final-missing','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    try:
        final=_read_json(final_path)
    except Exception as e:
        return {'state':'unknown','reason':type(e).__name__,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    if not isinstance(final,dict):
        return {'state':'unknown','reason':'final-object','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    attempted=final.get('attemptedSuites')
    if not isinstance(attempted,list):
        return {'state':'unknown','reason':'attempted-suites','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    rows=final.get('rows')
    if not isinstance(rows,list):
        return {'state':'unknown','reason':'final-rows','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    final_groups=final.get('groups')
    if not isinstance(final_groups,list):
        return {'state':'unknown','reason':'final-groups','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
    suites=[]
    for suite in attempted:
        if not isinstance(suite,str) or not suite or '/' in suite or suite in ('.','..'):
            return {'state':'unknown','reason':'attempted-suite','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
        if suite in suites:
            return {'state':'unknown','reason':'attempted-duplicate','groups':[],'count':0,'allAbsent':False,'attemptedSuites':[]}
        suites.append(suite)
    row_map={}
    for row in rows:
        if not isinstance(row,dict):
            return {'state':'unknown','reason':'row-shape','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        suite=row.get('suite')
        if not isinstance(suite,str) or suite not in suites:
            return {'state':'unknown','reason':'row-foreign','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if suite in row_map:
            return {'state':'unknown','reason':'row-duplicate','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if row.get('cleanupConfirmed') is not True:
            return {'state':'unknown','reason':'row-cleanup','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        row_map[suite]=row
    if set(row_map)!=set(suites):
        return {'state':'unknown','reason':'row-coverage','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
    group_map={}
    for group in final_groups:
        if not isinstance(group,dict):
            return {'state':'unknown','reason':'group-shape','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        suite=group.get('suite')
        if not isinstance(suite,str) or suite not in suites:
            return {'state':'unknown','reason':'group-foreign','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if suite in group_map:
            return {'state':'unknown','reason':'group-duplicate','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        group_map[suite]=group
    if set(group_map)!=set(suites):
        return {'state':'unknown','reason':'group-coverage','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
    expected_cwd=os.path.abspath(str(GUEST/'candidate'))
    checked=[]
    for suite in suites:
        parent=GUEST/'evidence'/suite
        if not _directory(parent):
            return {'state':'unknown','reason':'missing-group-directory:'+suite,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        ipath=parent/'intent.json';ppath=parent/'process.json';cpath=parent/'capture.json'
        for path in (ipath,ppath,cpath):
            if not _regular(path):
                return {'state':'unknown','reason':'missing-required:'+suite+':'+path.name,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        try:
            intent=_read_json(ipath)
        except Exception as e:
            return {'state':'unknown','reason':'intent-read:'+suite+':'+type(e).__name__,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if not isinstance(intent,dict) or intent.get('identityRequired') is not True or intent.get('createdBeforeProcess') is not True or intent.get('suite')!=suite or intent.get('cwd')!=expected_cwd:
            return {'state':'unknown','reason':'intent-mismatch:'+suite,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        try:
            process=_read_json(ppath)
        except Exception as e:
            return {'state':'unknown','reason':'process-read:'+suite+':'+type(e).__name__,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if not isinstance(process,dict) or process.get('originalPopenChild') is not True or not isinstance(process.get('identity'),dict):
            return {'state':'unknown','reason':'process-mismatch:'+suite,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        relation_ok,relation_why=_identity_relation(process,process.get('identity'))
        if not relation_ok:
            return {'state':'unknown','reason':'process-identity:'+suite+':'+str(relation_why),'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        try:
            capture=_read_json(cpath)
        except Exception as e:
            return {'state':'unknown','reason':'capture-read:'+suite+':'+type(e).__name__,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        if not isinstance(capture,dict) or capture.get('suite')!=suite or capture.get('cleanupConfirmed') is not True:
            return {'state':'unknown','reason':'capture-mismatch:'+suite,'groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
        checked.append((suite,process.get('identity')))
    fn=getattr(guard,'group_state',None)
    if not callable(fn):
        return {'state':'unknown','reason':'group-state-missing','groups':[],'count':0,'allAbsent':False,'attemptedSuites':suites}
    group_states=[]
    for suite,identity in checked:
        try:
            state=fn(identity)
        except Exception as e:
            return {'state':'unknown','reason':'group-query:'+suite+':'+type(e).__name__,'groups':group_states,'count':len(group_states),'allAbsent':False,'attemptedSuites':suites}
        if not isinstance(state,dict):
            return {'state':'unknown','reason':'group-query-shape:'+suite,'groups':group_states,'count':len(group_states),'allAbsent':False,'attemptedSuites':suites}
        group_states.append({'suite':suite,'state':state.get('state'),'query':'group_state'})
    if any(g.get('state')=='unknown' for g in group_states):state='unknown'
    elif any(not _state_exited(g) for g in group_states):state='present'
    else:state='absent'
    return {'state':state,'groups':group_states,'count':len(group_states),'allAbsent':state=='absent','attemptedSuites':suites}
def _containers(box):
    directory=box/'state/containers'
    if _absent(directory):return {'allRemoved':True,'count':0}
    if not _directory(directory):return {'allRemoved':False,'state':'unknown'}
    try:names=sorted(os.listdir(directory))
    except OSError as e:return {'allRemoved':False,'state':'unknown','reason':type(e).__name__}
    for name in names:
        if not name.endswith('.json'):return {'allRemoved':False,'count':len(names),'bad':name}
        path=directory/name
        if not _regular(path):return {'allRemoved':False,'count':len(names),'bad':name}
        try:record=_read_json(path)
        except Exception as e:return {'allRemoved':False,'count':len(names),'bad':name,'reason':type(e).__name__}
        if not isinstance(record,dict) or record.get('removed') is not True or record.get('status')!='removed':
            return {'allRemoved':False,'count':len(names),'bad':name}
    return {'allRemoved':True,'count':len(names)}
def _stage(cleanup,box):
    if not isinstance(cleanup,dict):return {'state':'unknown','reason':'cleanup-object'}
    inner=cleanup.get('cleanup')
    stage=inner.get('stage') if isinstance(inner,dict) else None
    if not isinstance(stage,dict):return {'state':'unknown','reason':'stage-object'}
    text=stage.get('path')
    if not isinstance(text,str) or not text:return {'state':'unknown','reason':'stage-path'}
    path=Path(text)
    if not path.is_absolute() or path==box or '..' in path.parts:return {'state':'unknown','reason':'stage-path'}
    try:path.relative_to(box)
    except ValueError:return {'state':'unknown','reason':'stage-outside'}
    if not _no_symlink_parents(box,path):return {'state':'unknown','reason':'stage-parent-link'}
    try:os.lstat(path)
    except FileNotFoundError:return {'state':'absent','path':str(path)}
    except OSError as e:return {'state':'unknown','path':str(path),'reason':type(e).__name__}
    return {'state':'present','path':str(path)}
def _inner(guard):
    path=RUN/'consumer-12.json'
    if not _regular(path):return [],{'state':'unknown','reason':'no-consumer-results'}
    try:result=_read_json(path)
    except Exception as e:return [],{'state':'unknown','reason':type(e).__name__}
    retained=result.get('retainedSandboxes') if isinstance(result,dict) else None
    if not isinstance(retained,list) or len(retained)!=1:return [],{'state':'unknown','reason':'retained-count'}
    entry=retained[0]
    if not isinstance(entry,dict):return [],{'state':'unknown','reason':'retained-object'}
    if entry.get('caseId')!=FINAL_CASE_ID:return [],{'state':'unknown','reason':'retained-case'}
    rel=entry.get('relativePath')
    if not isinstance(rel,str) or SANDBOX_RE.fullmatch(rel) is None:return [],{'state':'unknown','reason':'retained-path'}
    base=GUEST/'candidate'
    if not _no_symlink_components(base,rel):return [],{'state':'unknown','reason':'retained-symlink'}
    box=base/rel
    if not _directory(box):return [],{'state':'unknown','reason':'retained-directory'}
    evroot=box/'preflight/evidence'
    if not _directory(evroot):return [],{'state':'unknown','reason':'preflight-directory'}
    try:names=sorted(os.listdir(evroot))
    except OSError as e:return [],{'state':'unknown','reason':type(e).__name__}
    if len(names)!=1 or PREFLIGHT_RE.fullmatch(names[0]) is None:return [],{'state':'unknown','reason':'preflight-count'}
    evidence=evroot/names[0]
    if not _directory(evidence):return [],{'state':'unknown','reason':'preflight-entry'}
    role_states={}
    for role in ('client','observer'):
        p=evidence/('process-'+role+'-identity.json')
        if not _regular(p):return [],{'state':'unknown','reason':'identity:'+role}
        try:record=_read_json(p)
        except Exception as e:return [],{'state':'unknown','reason':type(e).__name__}
        if not isinstance(record,dict) or record.get('role')!=role or record.get('preflightId')!=evidence.name:
            return [],{'state':'unknown','reason':'identity-bind:'+role}
        try:role_states[role]=guard.spawn_group_state(record)
        except Exception as e:role_states[role]={'state':'unknown','errorType':type(e).__name__}
    cleanup_path=evidence/'cleanup.json'
    if not _regular(cleanup_path):return [],{'state':'unknown','reason':'cleanup-missing'}
    try:cleanup=_read_json(cleanup_path)
    except Exception as e:return [],{'state':'unknown','reason':type(e).__name__}
    stage=_stage(cleanup,box)
    containers=_containers(box)
    ok=all(_state_exited(v) for v in role_states.values()) and len(role_states)==2 and stage.get('state')=='absent' and containers.get('allRemoved') is True
    return [{'box':rel,'preflightEvidence':evidence.name,'roleStates':role_states,'stage':stage,'containers':containers,'ok':ok}],None
def main(expected):
    result={'kind':'guest-readonly-status','guestRoot':str(GUEST),'controller':{'state':'unknown'},'batchLock':{'state':'unknown','released':False},'outerGroup':{'state':'unknown'},'outerGroups':{'state':'unknown'},'inner':[],'idleConfirmed':False,'errors':[],'filesWritten':False,'nonzeroSignalsSent':0,'formalTargets':'0/16','r3':'blocked'}
    if sys.platform!='linux' or os.getuid()!=UID:
        result['errors'].append({'reason':'host'})
        return result
    ok,reason=_root_check()
    if not ok:
        if reason=='absent':result['controller']={'state':'original-attempt-absent'}
        else:result['errors'].append({'reason':'root','detail':reason})
        return result
    verified,problems=_verify_expected(expected)
    if not verified:
        for problem in problems:result['errors'].append({'reason':problem})
        return result
    final_path=GUEST/'final.json'
    if not _regular(final_path):
        result['errors'].append({'reason':'final-missing'})
        return result
    try:final=_read_json(final_path)
    except Exception as e:
        result['errors'].append({'reason':'final-read','errorType':type(e).__name__})
        return result
    if not isinstance(final,dict):
        result['errors'].append({'reason':'final-object'})
        return result
    attempt_path=GUEST/'attempt.json'
    if not _regular(attempt_path):
        result['errors'].append({'reason':'attempt-missing'})
        return result
    try:attempt=_read_json(attempt_path)
    except Exception as e:
        result['errors'].append({'reason':'attempt-read','errorType':type(e).__name__})
        return result
    if not isinstance(attempt,dict):
        result['errors'].append({'reason':'attempt-object'})
        return result
    expected_root=expected.get('guestRoot') if isinstance(expected,dict) else None
    expected_source=expected.get('sourceManifestSha256') if isinstance(expected,dict) else None
    if isinstance(expected_root,str):
        if 'guestRoot' in final and final.get('guestRoot')!=expected_root:
            result['errors'].append({'reason':'final-guest-root'})
            return result
        if 'guestRoot' in attempt and attempt.get('guestRoot')!=expected_root:
            result['errors'].append({'reason':'attempt-guest-root'})
            return result
    if 'sourceManifestSha256' in final:
        if not isinstance(expected_source,str) or final.get('sourceManifestSha256')!=expected_source:
            result['errors'].append({'reason':'final-source-sha'})
            return result
    if 'sourceManifestSha256' in attempt:
        if not isinstance(expected_source,str) or attempt.get('sourceManifestSha256')!=expected_source:
            result['errors'].append({'reason':'attempt-source-sha'})
            return result
    try:
        guard_raw=_expected_raw(expected,'candidate/tools/resource_guard.py')
        batch_raw=_expected_raw(expected,'operator/full20_batch.py')
        batch=_compile_verified_module('status_full20_batch',GUEST/'operator/full20_batch.py',batch_raw)
    except Exception as e:
        result['errors'].append({'reason':'verified-helper-load','errorType':type(e).__name__})
        return result
    try:guard=_load_guard(guard_raw)
    except Exception as e:
        result['errors'].append({'reason':'guard-load','errorType':type(e).__name__})
        return result
    if not callable(getattr(batch,'_safe_quiescence',None)) or not callable(getattr(batch,'resources_confirmed',None)):
        result['errors'].append({'reason':'batch-helper-missing'})
        return result
    outer=_outer_groups(guard);result['outerGroups']=outer
    result['outerGroup']={'state':outer.get('state'),'groups':outer.get('groups'),'count':outer.get('count'),'allAbsent':outer.get('allAbsent')}
    if outer.get('state')=='unknown':
        result['errors'].append({'reason':'outer','detail':outer.get('reason')})
        return result
    lock=_batch_lock();result['batchLock']=lock
    controller={k:attempt.get(k) for k in ('pid','pgid','starttime','bootId')}
    try:controller['state']=guard.process_state(attempt)
    except Exception as e:controller['state']={'state':'unknown','errorType':type(e).__name__}
    result['controller']=controller
    inner,unknown=_inner(guard);result['inner']=inner
    if unknown:result['errors'].append({'reason':'inner','detail':unknown})
    roles=inner[0].get('roleStates',{}) if inner else {}
    attempted=final.get('attemptedSuites');rows=final.get('rows')
    strict_ok=False;strict_detail={'state':'unknown','reason':'strict-not-run'};strict_resources=False
    try:
        strict_ok,strict_detail=batch._safe_quiescence(GUEST,{'candidate/tools/resource_guard.py':guard_raw},attempted,rows)
        strict_resources=batch.resources_confirmed({'resourceQuiescent':strict_ok,'actualProcessQuiescence':strict_detail,'attemptedSuites':attempted,'rows':rows})
    except Exception as e:
        strict_detail={'state':'unknown','reason':'strict-exception','errorType':type(e).__name__}
    result['strictResourceQuiescence']={'ok':strict_ok is True,'confirmed':strict_resources is True,'detail':strict_detail}
    conditions={'batchLockReleased':lock.get('released') is True,'controllerExited':_state_exited(controller.get('state')),'outerGroupsAbsent':outer.get('allAbsent') is True,'consumer12Submitted':'consumer-12' in outer.get('attemptedSuites',[]),'twoRolesExited':len(roles)==2 and all(_state_exited(v) for v in roles.values()),'stageAbsent':bool(inner) and inner[0].get('stage',{}).get('state')=='absent','containersRemoved':bool(inner) and inner[0].get('containers',{}).get('allRemoved') is True,'strictResourcesConfirmed':strict_ok is True and strict_resources is True}
    result['conditions']=conditions
    result['idleConfirmed']=all(conditions.values())
    return result
