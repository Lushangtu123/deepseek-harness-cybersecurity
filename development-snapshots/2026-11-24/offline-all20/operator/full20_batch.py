'''Isolated full20 Linux batch operator. Read-only resource query; no arbitrary signals.'''
from pathlib import Path,PurePosixPath
from hashlib import sha256
import importlib.util,json,os,stat,sys,time,types
R=Path(__file__).resolve().parents[1]
C=R/'candidate'
RUN=C/'checks/evidence-runs/full20-linux-20261123'
CAP=67108864
STOP=4194304
FLOOR=536870912
ORDER=('consumer-12','evidence-gate','record-validation-15','unified-recovery-27','association-recovery-21','recovery-close-24','formal-admission-15','original-28','end-lf-13','rev6-24','rev7-12','rev8-13','diagnostics-20','repair-11','buffer-preflight-29','pure-compile','buffer-red-6','baseline-verify','independent-116','static')
SUITES=frozenset(ORDER)
BATCH_DEADLINE_SECONDS=2700
def require(ok,reason):
 if not ok:raise ValueError(reason)
def _hex64(v):
 return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)
def _valid_rel(name):
 if not isinstance(name,str):return False
 p=PurePosixPath(name)
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
def _no_symlink_components(base,rel):
 cur=Path(base)
 if not _directory(cur):return False
 for part in PurePosixPath(rel).parts:
  cur=cur/part
  try:info=os.lstat(cur)
  except OSError:return False
  if stat.S_ISLNK(info.st_mode):return False
 return True
def _read_json(path):
 with open(path,'rb') as f:return json.loads(f.read())
def _raw_bytes(value):
 if isinstance(value,bytes):return value
 if isinstance(value,str):return value.encode('utf-8')
 raise ValueError('immutable-value')
def _load_path(name,path):
 s=importlib.util.spec_from_file_location(name,str(path));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def validate_registry(plan,source_sha):
 require(isinstance(plan,dict),'plan-object')
 require(isinstance(source_sha,str) and _hex64(source_sha),'source-sha')
 require(plan.get('sourceManifestSha256')==source_sha,'source-sha')
 require(plan.get('allFresh') is True,'plan-fresh')
 require(plan.get('noHistoricalOrSyntheticResults') is True,'plan-synthetic')
 order=plan.get('order')
 require(type(order) is list and tuple(order)==ORDER,'registry-order')
 require(order[0]=='consumer-12' and order[-1]=='static','registry-ends')
 require(len(order)==20 and len(set(order))==20,'registry-membership')
 suites=plan.get('suites')
 require(isinstance(suites,dict) and set(suites)==SUITES,'registry-suites')
 seen=set()
 for suite in ORDER:
  row=suites[suite]
  require(isinstance(row,dict),'suite-row')
  command=row.get('command')
  require(type(command) is list and command,'suite-command')
  require(all(type(x) is str for x in command),'suite-argv')
  require(command[0]=='{PYTHON}','suite-interpreter')
  require('-I' in command and '-B' in command,'suite-isolation')
  for token in command:
   require(token not in ('-O','-OO') and not token.startswith('-O'),'suite-opt')
  result=row.get('resultName')
  require(type(result) is str and result and '/' not in result and result.endswith('.json'),'suite-result')
  require(result not in seen,'suite-result-duplicate')
  seen.add(result)
 return True
def validate_binding(manifest_raw,registry_raw,admitted_sha):
 require(isinstance(manifest_raw,bytes),'manifest-raw')
 require(isinstance(registry_raw,bytes),'registry-raw')
 require(isinstance(admitted_sha,str) and _hex64(admitted_sha),'admitted-sha')
 require(sha256(manifest_raw).hexdigest()==admitted_sha,'admitted-manifest-digest')
 try:manifest=json.loads(manifest_raw)
 except Exception as error:raise ValueError('manifest-parse:'+type(error).__name__)
 require(isinstance(manifest,dict),'manifest-object')
 try:plan=json.loads(registry_raw)
 except Exception as error:raise ValueError('registry-parse:'+type(error).__name__)
 validate_registry(plan,admitted_sha)
 return plan
def _command(plan,suite,root):
 c=root/'candidate';run=c/'checks/evidence-runs/full20-linux-20261123'
 values={'{PYTHON}':sys.executable,'{CANDIDATE}':str(c),'{RUN}':str(run),'{OPERATOR}':str(root/'operator'),'{AUX}':str(root/'checks/independent'),'{REFERENCES}':str(root/'references')}
 result=[]
 for raw in plan['suites'][suite]['command']:
  for key,value in values.items():raw=raw.replace(key,value)
  require('{' not in raw and '}' not in raw,'unresolved-command')
  result.append(raw)
 require(result[0]==sys.executable and '-I' in result and '-B' in result and not any(x in ('-O','-OO') or x.startswith('-O') for x in result),'command-interpreter')
 return result
def _verify_files(root,files):
 require(isinstance(files,dict) and files,'immutable-map')
 for name,value in files.items():
  require(_valid_rel(name),'immutable-path')
  require(_no_symlink_components(root,name),'immutable-link:'+name)
  path=root/name
  require(_regular(path),'immutable-regular:'+name)
  require(path.read_bytes()==_raw_bytes(value),'immutable-changed:'+name)
 return True
def _resource_log_empty(root):
 path=root/'evidence/unexpected-resource-calls.log'
 try:info=os.lstat(path)
 except FileNotFoundError:return False,'missing'
 except OSError as e:return False,type(e).__name__
 if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):return False,'not-regular'
 return info.st_size==0,None
def _capacity(root,bounded,planned=STOP):
 used=bounded.usage(root)
 st=os.statvfs(root);free=st.f_bavail*st.f_frsize
 require(used<=CAP-STOP,'capacity-used')
 require(free>=FLOOR,'capacity-free')
 require(bounded.budget_admitted(used,free,planned),'capacity-admission')
 return used,free
def _exited(value):
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
def _load_guard(root,files):
 name='candidate/tools/resource_guard.py'
 path=root/name
 require(_regular(path),'guard-missing')
 raw=path.read_bytes()
 require(raw==_raw_bytes(files[name]),'guard-changed')
 mod=types.ModuleType('resource_guard');mod.__file__=str(path)
 exec(compile(raw,mod.__file__,'exec'),mod.__dict__)
 sys.modules['resource_guard']=mod
 return mod
def _actual_process_quiescence(root,files,attempted_suites=None,rows=None):
 root=Path(root);actual=[];skipped=[]
 batch_context=attempted_suites is not None
 attempted=[];row_map={}
 def unknown(reason,**extra):
  detail={'state':'unknown','reason':reason,'records':actual,'skipped':skipped}
  detail.update(extra)
  return False,detail
 if batch_context:
  if not isinstance(attempted_suites,list):return unknown('attempted-suites-shape')
  for suite in attempted_suites:
   if not isinstance(suite,str) or not suite or '/' in suite or suite in ('.','..'):return unknown('attempted-suite-invalid',suite=str(suite)[:80])
   if suite in attempted:return unknown('attempted-suite-duplicate',suite=suite)
   attempted.append(suite)
  if not isinstance(rows,list):return unknown('rows-shape')
  for row in rows:
   if not isinstance(row,dict):return unknown('row-shape')
   suite=row.get('suite')
   if not isinstance(suite,str) or suite not in attempted:return unknown('row-foreign',suite=str(suite)[:80])
   if suite in row_map:return unknown('row-duplicate',suite=suite)
   if row.get('cleanupConfirmed') is not True:return unknown('row-cleanup-unconfirmed',suite=suite)
   row_map[suite]=row
  if set(row_map)!=set(attempted):return unknown('row-coverage',missing=[s for s in attempted if s not in row_map])
 else:
  if rows is not None:return unknown('rows-without-attempts')
 try:guard=_load_guard(root,files)
 except BaseException as error:return unknown('guard-load',errorType=type(error).__name__)
 for rel in ('candidate','evidence'):
  if not _directory(root/rel):return unknown('required-tree:'+rel)
 expected_cwd=os.path.abspath(str(root/'candidate'))
 validated=set()
 def walk_error(error):raise ValueError('walk:'+type(error).__name__+':'+str(getattr(error,'filename','')))
 def validate_wrapper(parent,suite_hint=None):
  parent=Path(parent)
  try:parent_rel=str(parent.relative_to(root))
  except Exception:return unknown('wrapper-path')
  if not _directory(parent):return unknown('wrapper-directory',record=parent_rel)
  ipath=parent/'intent.json';ppath=parent/'process.json';cpath=parent/'capture.json'
  if not os.path.lexists(ipath):return unknown('missing-required-intent',record=parent_rel)
  if not _regular(ipath):return unknown('intent-record-special',record=str(ipath.relative_to(root)))
  try:intent=_read_json(ipath)
  except BaseException as error:return unknown('intent-record-read',record=str(ipath.relative_to(root)),errorType=type(error).__name__)
  if not isinstance(intent,dict):return unknown('intent-record-shape',record=str(ipath.relative_to(root)))
  if intent.get('identityRequired') is not True:return unknown('intent-identity-required',record=str(ipath.relative_to(root)))
  if intent.get('createdBeforeProcess') is not True:return unknown('intent-created-before-process',record=str(ipath.relative_to(root)))
  suite=intent.get('suite')
  if not isinstance(suite,str) or not suite or '/' in suite or suite in ('.','..'):return unknown('intent-suite-invalid',record=str(ipath.relative_to(root)))
  if suite_hint is not None and suite!=suite_hint:return unknown('intent-suite-mismatch',record=str(ipath.relative_to(root)))
  if parent.name!=suite:return unknown('intent-path-mismatch',record=str(ipath.relative_to(root)))
  cwd=intent.get('cwd')
  if not isinstance(cwd,str) or os.path.abspath(cwd)!=expected_cwd:return unknown('intent-cwd-mismatch',record=str(ipath.relative_to(root)))
  if not os.path.lexists(ppath):return unknown('missing-required-process',record=str(ppath.relative_to(root)))
  if not _regular(ppath):return unknown('process-record-special',record=str(ppath.relative_to(root)))
  try:record=_read_json(ppath)
  except BaseException as error:return unknown('process-record-read',record=str(ppath.relative_to(root)),errorType=type(error).__name__)
  if not isinstance(record,dict):return unknown('process-record-shape',record=str(ppath.relative_to(root)))
  if record.get('originalPopenChild') is not True:return unknown('process-record-unclassified',record=str(ppath.relative_to(root)))
  ok,why=_identity_relation(record,record.get('identity'))
  if not ok:return unknown('wrapper-identity:'+str(why),record=str(ppath.relative_to(root)))
  fn=getattr(guard,'group_state',None)
  if not callable(fn):return unknown('group-state-missing',record=str(ppath.relative_to(root)))
  try:state=fn(record.get('identity'))
  except BaseException as error:return unknown('query-exception',query='group_state',record=str(ppath.relative_to(root)),errorType=type(error).__name__)
  actual.append({'record':str(ppath.relative_to(root)),'query':'group_state','state':state if isinstance(state,dict) else {'state':'unknown','detail':'query-shape'}})
  if not _exited(state):return unknown('not-exited',state=state.get('state') if isinstance(state,dict) else 'unknown',record=str(ppath.relative_to(root)))
  cap_needed=True
  if cap_needed or os.path.lexists(cpath):
   if not os.path.lexists(cpath):return unknown('missing-capture',record=str(cpath.relative_to(root)))
   if not _regular(cpath):return unknown('capture-record-special',record=str(cpath.relative_to(root)))
   try:capture=_read_json(cpath)
   except BaseException as error:return unknown('capture-record-read',record=str(cpath.relative_to(root)),errorType=type(error).__name__)
   if not isinstance(capture,dict):return unknown('capture-record-shape',record=str(cpath.relative_to(root)))
   if capture.get('suite')!=suite:return unknown('capture-suite-mismatch',record=str(cpath.relative_to(root)))
   if capture.get('cleanupConfirmed') is not True:return unknown('capture-cleanup-unconfirmed',record=str(cpath.relative_to(root)))
  validated.add(str(parent))
  return None
 evidence=root/'evidence'
 try:
  for entry in sorted(os.scandir(evidence),key=lambda x:x.name):
   try:info=entry.stat(follow_symlinks=False)
   except OSError as error:return unknown('walk-entry:'+type(error).__name__,record=entry.name)
   if stat.S_ISLNK(info.st_mode):return unknown('linked-directory',record=entry.name)
   if not stat.S_ISDIR(info.st_mode):continue
   parent=Path(entry.path)
   ipath=parent/'intent.json';ppath=parent/'process.json'
   if not os.path.lexists(ipath) and not os.path.lexists(ppath):continue
   result=validate_wrapper(parent,parent.name)
   if result is not None:return result
 except OSError as error:return unknown('evidence-scan:'+type(error).__name__)
 for suite in attempted:
  parent=evidence/suite
  if str(parent) in validated:continue
  if not _directory(parent):return unknown('missing-attempt-directory',suite=suite)
  result=validate_wrapper(parent,suite)
  if result is not None:return result
 for rel in ('candidate','evidence'):
  base=root/rel
  try:
   for directory,dirs,names in os.walk(base,followlinks=False,onerror=walk_error):
    for d in dirs:
     path=Path(directory)/d
     try:info=os.lstat(path)
     except OSError as error:return unknown('walk-entry:'+type(error).__name__,record=str(path.relative_to(root)))
     if stat.S_ISLNK(info.st_mode):return unknown('linked-directory',record=str(path.relative_to(root)))
     if not stat.S_ISDIR(info.st_mode):return unknown('special-directory',record=str(path.relative_to(root)))
    for name in names:
     path=Path(directory)/name;record_rel=str(path.relative_to(root))
     try:
      info=os.lstat(path)
     except OSError as error:return unknown('walk-entry:'+type(error).__name__,record=record_rel)
     if stat.S_ISLNK(info.st_mode):return unknown('linked-file',record=record_rel)
     if name=='process.json':
      path=Path(directory)/name
      parent=path.parent
      if str(parent) in validated:continue
      result=validate_wrapper(parent,parent.name)
      if result is not None:return result
      continue
     if not (name.startswith('process-') and name.endswith('-identity.json')):continue
     path=Path(directory)/name;record_rel=str(path.relative_to(root))
     try:
      if not _regular(path):raise ValueError('process-record-special')
      record=_read_json(path)
     except BaseException as error:return unknown('process-record-read',record=record_rel,errorType=type(error).__name__)
     if not isinstance(record,dict):return unknown('process-record-shape',record=record_rel)
     is_role=record.get('role') in ('client','observer') and isinstance(record.get('preflightId'),str)
     if not is_role:return unknown('process-record-unclassified',record=record_rel)
     try:
      fn=getattr(guard,'spawn_group_state',None)
      if not callable(fn):return unknown('spawn-group-state-missing',record=record_rel)
      state=fn(record)
     except BaseException as error:return unknown('query-exception',query='spawn_group_state',record=record_rel,errorType=type(error).__name__)
     actual.append({'record':record_rel,'query':'spawn_group_state','state':state if isinstance(state,dict) else {'state':'unknown','detail':'query-shape'}})
     if not _exited(state):return unknown('not-exited',state=state.get('state') if isinstance(state,dict) else 'unknown',record=record_rel)
  except BaseException as error:return unknown('walk-failure',errorType=type(error).__name__)
 return True,{'state':'quiescent','records':actual,'skipped':skipped}
def _safe_quiescence(root,files,attempted_suites=None,rows=None):
 try:ok,detail=_actual_process_quiescence(root,files,attempted_suites,rows)
 except BaseException as error:return False,{'state':'unknown','reason':'quiescence-exception','errorType':type(error).__name__,'message':str(error)[:300]}
 if not isinstance(detail,dict):return False,{'state':'unknown','reason':'quiescence-detail'}
 return bool(ok),detail
def resources_confirmed(batch_result):
 try:
  if not isinstance(batch_result,dict):return False
  if batch_result.get('resourceQuiescent') is not True:return False
  detail=batch_result.get('actualProcessQuiescence')
  if not isinstance(detail,dict) or detail.get('state')!='quiescent':return False
  attempted=batch_result.get('attemptedSuites');rows=batch_result.get('rows')
  if not isinstance(attempted,list) or not isinstance(rows,list):return False
  seen=set()
  for suite in attempted:
   if not isinstance(suite,str) or not suite or '/' in suite or suite in ('.','..'):return False
   if suite in seen:return False
   seen.add(suite)
  row_map={}
  for row in rows:
   if not isinstance(row,dict):return False
   suite=row.get('suite')
   if not isinstance(suite,str) or suite not in seen:return False
   if suite in row_map:return False
   if row.get('cleanupConfirmed') is not True:return False
   row_map[suite]=row
  if set(row_map)!=seen:return False
  return True
 except BaseException:return False
def run_batch(root,packet,files,bounded,helpers,audit_consumer):
 root=Path(root);c=root/'candidate';run=c/'checks/evidence-runs/full20-linux-20261123'
 plan=_read_json(root/'operator/suite-plan.json')
 source_sha=packet.get('sourceManifestSha256') if isinstance(packet,dict) else None
 validate_registry(plan,source_sha)
 g=_load_path('frozen_full20_reader',c/'checks/finalize_closure.py')
 expected=g._FIXED_COUNTS
 require(set(plan['order'])==set(expected) and len(plan['order'])==20,'reader-registry')
 _verify_files(root,files)
 guard=_load_guard(root,files)
 identity_reader=getattr(guard,'process_identity',None)
 require(callable(identity_reader),'identity-reader-callable')
 require(_absent(run),'existing-run')
 _capacity(root,bounded,STOP)
 rows=[];captures=[];groups=[];attempted=[];problem=None;stopped_suite=None;consumer_audit=None
 deadline=time.monotonic()+BATCH_DEADLINE_SECONDS
 initial_quiescent,qdetails=_safe_quiescence(root,files,attempted,rows)
 if not initial_quiescent:
  problem={'suite':'resource-initial','type':'resource-quiescence','message':str(qdetails.get('state','unknown'))[:700]}
  stopped_suite='resource-initial'
 else:
  try:
   run.mkdir(parents=True,mode=0o700)
   for suite in plan['order']:
    if time.monotonic()>=deadline:
     problem={'suite':suite,'type':'batch-deadline','message':'batch deadline exceeded before group'}
     stopped_suite=suite
     break
    group={'suite':suite};row=None
    try:
     _verify_files(root,files)
     ok,why=_resource_log_empty(root);require(ok,'resource-log:'+str(why))
     _capacity(root,bounded,STOP)
     output=run/plan['suites'][suite]['resultName'];capdir=run/'raw'/suite
     require(_absent(output) and _absent(capdir),'existing-suite-output:'+suite)
     producer=_command(plan,suite,root)
     source_before=g._source_state(c)
     require(source_before.get('manifestSha256')==source_sha,'source-before')
     group.update({'command':producer,'result':str(output),'capture':str(capdir/'run.json'),'sourceBefore':source_before.get('manifestSha256')})
     def validate(value,suite=suite):
      source=g._source_state(c);require(source.get('manifestSha256')==source_sha,'reader-source-changed')
      if suite=='baseline-verify':return g._validate_baseline_entry(value,c)
      if suite=='independent-116':return g._validate_independent_entry(value,suite,source)
      return g._validate_ordinary_entry(value,suite,source,'offline-closure')
     n=1 if suite=='baseline-verify' else expected[suite]
     args=[sys.executable,'-I','-B',str(c/'checks/evidence_capture.py'),'--suite',suite,'--source-root',str(c),'--run-dir',str(capdir),'--result',str(output),'--timeout','100','--',*producer]
     attempted.append(suite)
     row=bounded.run_one(root,suite,args,n,sorted(files),result_file=str(output),validator=validate,seconds=120,identity_reader=identity_reader)
     rows.append(row);group['rowIndex']=len(rows)-1
     if row.get('passed') is not True:raise ValueError('suite-failed:'+str(row.get('problem')))
     source_after=g._source_state(c)
     group['sourceAfter']=source_after.get('manifestSha256')
     require(source_after.get('manifestSha256')==source_sha,'source-after')
     _verify_files(root,files)
     ok,why=_resource_log_empty(root);require(ok,'resource-log:'+str(why))
     resolved=g.resolve_capture_artifacts(c,(capdir/'run.json').relative_to(c).as_posix(),None)
     cap=resolved['capture']
     require(cap.get('suite')==suite and cap.get('command')==producer and type(cap.get('returncode')) is int and cap.get('returncode')==0,'capture-command-or-code')
     require(cap.get('sourceUnchanged') is True and cap.get('sourceClosureOk') is True,'capture-source-state')
     for side in ('sourceManifestBefore','sourceManifestAfter'):
      snap=cap.get(side)
      require(isinstance(snap,dict) and snap.get('ok') is True and snap.get('manifestSha256')==source_sha and snap.get('entries')==source_after.get('actual'),'capture-source-map')
     counts=validate(resolved['result']);group['validationCounts']=list(counts)
     group['captureSha256']=sha256((capdir/'run.json').read_bytes()).hexdigest()
     captures.append(str(capdir/'run.json'))
     if suite=='consumer-12':
      result_json=_read_json(output)
      ok,details,audit_errors=audit_consumer(result_json,files)
      require(ok,'consumer-audit')
      consumer_audit={'ok':True,'details':details,'errors':audit_errors};group['consumerAudit']=consumer_audit
     groups.append(group)
     post_ok,post_details=_safe_quiescence(root,files,attempted,rows)
     group['resourceQuiescence']=post_details
     if not post_ok:
      problem={'suite':suite,'type':'resource-quiescence','message':str(post_details.get('state','unknown'))[:700]}
      stopped_suite=suite
      break
    except BaseException as error:
     if row is not None and (not rows or rows[-1] is not row):rows.append(row)
     group['error']={'type':type(error).__name__,'message':str(error)[:700]}
     groups.append(group)
     problem={'suite':suite,'type':type(error).__name__,'message':str(error)[:700]}
     stopped_suite=suite
     break
  except BaseException as error:
   problem={'suite':'batch','type':type(error).__name__,'message':str(error)[:700]}
 all_source=True
 try:_verify_files(root,files)
 except Exception as error:
  all_source=False;problem=problem or {'suite':'source','type':type(error).__name__,'message':str(error)[:700]}
 final_quiescent,qdetails=_safe_quiescence(root,files,attempted,rows)
 quiescent=resources_confirmed({'resourceQuiescent':final_quiescent,'actualProcessQuiescence':qdetails,'attemptedSuites':attempted,'rows':rows})
 if not quiescent and problem is None:problem={'suite':stopped_suite or 'resource','type':'resource-quiescence','message':str(qdetails.get('state','unknown'))[:700]}
 log_ok,log_why=_resource_log_empty(root)
 if not log_ok and problem is None:problem={'suite':'resource-log','type':'unexpected-resource-command','message':str(log_why)[:700]}
 returned_exited=len(rows)==20 and all(isinstance(r,dict) and r.get('cleanupConfirmed') is True for r in rows)
 if not returned_exited and problem is None:problem={'suite':stopped_suite or plan['order'][min(len(rows),19)],'type':'outer-group-exit','message':'wrapper exit evidence incomplete'}
 complete=problem is None and len(captures)==20 and len(rows)==20 and consumer_audit is not None and consumer_audit.get('ok') is True and all_source and quiescent and log_ok and returned_exited
 publication=None
 if complete and time.monotonic()>=deadline:
  complete=False
  problem={'suite':'publication','type':'batch-deadline','message':'batch deadline exceeded before finalization'}
 if complete:
  try:
   for name in ('checks-evidence-index.json','proof.json','REPORT.md','closure-manifest.json','phase-result.json'):require(_absent(c/name),'existing-publication:'+name)
   readset=0
   for path in captures:
    resolved=g.resolve_capture_artifacts(c,Path(path).relative_to(c).as_posix(),None)
    readset+=sum(a['bytes'] for a in resolved['artifacts'])
   st=os.statvfs(root);free=st.f_bavail*st.f_frsize
   require(bounded.budget_admitted(bounded.usage(root),free,readset+2097152),'seal-capacity')
   idx=g.build_evidence_index(c,captures,c/'checks-evidence-index.json')
   proof=g.build_proof(c,c/'checks-evidence-index.json',c/'proof.json')
   phase={'kind':'full20-linux-regression-phase','version':1,'state':'pending-independent-review','sourceManifestSha256':source_sha,'expectedGroups':20,'completedGroups':len(captures),'attemptedSuites':attempted,'resourceQuiescent':quiescent,'sourceUnchanged':all_source,'formalTargets':'0/16','r3':'blocked'}
   bounded.write_json(c/'phase-result.json',phase)
   gate=g.run_gate(c,c/'checks-evidence-index.json',c/'proof.json',c/'phase-result.json',c/'REPORT.md',c/'closure-manifest.json')
   require(isinstance(gate,dict) and gate.get('state')=='pending-independent-review' and gate.get('archiveCalls')==0,'report-proof-seal-failed')
   publication={'index':idx,'proof':{'ok':proof.get('ok'),'sha256':proof.get('sha256')},'gate':gate,'operatorArchivePending':True}
  except BaseException as error:
   publication=None;complete=False;problem={'suite':'publication','type':type(error).__name__,'message':str(error)[:700]}
 used=bounded.usage(root)
 return {'kind':'full20-linux-batch-result','full20':True,'state':'pending-final-review' if complete else 'stopped','complete':complete,'sourceManifestSha256':source_sha,'rows':rows,'attemptedSuites':attempted,'failedGroup':stopped_suite or (problem.get('suite') if isinstance(problem,dict) else None),'problem':problem,'captures':captures,'groups':groups,'actualCompleteCaptures':len(captures),'expectedGroups':20,'consumerAudit':consumer_audit,'publication':publication,'usedBytes':used,'capBytes':CAP,'allReturnedGroupsExited':returned_exited,'sourceUnchanged':all_source,'actualProcessQuiescence':qdetails,'resourceQuiescent':quiescent,'noHistoricalDirectoryCleanup':True,'noReplay':True,'newVMTests':0,'formalTargets':'0/16','r3':'blocked'}
