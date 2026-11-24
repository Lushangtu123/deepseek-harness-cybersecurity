"""Pinned VM-only execution observer. Not an in-process security boundary or remote attestation."""
import ast
import base64
import builtins
import contextlib
import dis
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

PROBES=["'harness-control'",'str(101+37)#','__harness_probe__=101+37',"'"]
POLICY={'version':1,'maxInputs':4,'inputSeconds':5,'pointSeconds':30,'memoryMiB':512,'cpus':1,'pids':64,'tmpMiB':32,'outputBytes':262144,'network':'none','proof':'python-narrow-literal-1'}
HASH=re.compile(r'[a-f0-9]{64}');NAME=re.compile(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/){0,12}[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py')
def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
def validate_contract(v):
 if (not isinstance(v,dict) or set(v)!={'version','path','entry','inputContract'} or type(v['version']) is not int or v['version']!=1
     or not isinstance(v['path'],str) or not NAME.fullmatch(v['path']) or v['inputContract']!='untrusted-data-only' or not isinstance(v['entry'],dict)):raise ValueError('Invalid execution contract')
 e=v['entry']
 if e.get('kind')=='function':
  if set(e)!={'kind','name','parameter'} or any(not isinstance(e[k],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',e[k]) for k in ['name','parameter']):raise ValueError('Invalid function recipe')
 elif e.get('kind')=='flask':
  if set(e)!={'kind','app','factory','method','path','input','key','resources'} or e['app']!='app' or e['factory'] not in {None,'init'} or e['method'] not in {'GET','POST'} or e['input'] not in {'query','cookie','form'} or not isinstance(e['path'],str) or not e['path'].startswith('/') or len(e['path'])>256 or not isinstance(e['key'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',e['key']) or not isinstance(e['resources'],dict) or len(e['resources'])>8:raise ValueError('Invalid Flask recipe')
  for name,text in e['resources'].items():
   if name not in {'access_log.txt','error_log.txt','templates/index.html','templates/404.html'} or not isinstance(text,str) or len(text.encode())>4096:raise ValueError('Unsupported fixture resource')
 else:raise ValueError('Unsupported entry')
 return v

def passive_source(source):
 try:tree=ast.parse(source)
 except (ValueError,SyntaxError,RecursionError):return False
 forbidden={'sys','ctypes','inspect','dis','marshal','gc','importlib','globals','locals','vars','getattr','setattr','delattr','__import__','compile','breakpoint'}
 for n in ast.walk(tree):
  if isinstance(n,ast.Name) and n.id in forbidden:return False
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   names=[a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [(n.module or '').split('.')[0]]
   if any(x in forbidden for x in names):return False
  if isinstance(n,ast.Attribute) and (n.attr.startswith('__') or n.attr in {'_getframe','settrace','setprofile','monitoring'}):return False
 return True

def literal_expression(text):
 if type(text) is not str or len(text)>256:return False
 try:node=ast.parse(text,mode='eval').body
 except (SyntaxError,ValueError,RecursionError):return False
 return isinstance(node,ast.Constant) and type(node.value) in {str,int,float,bool,type(None)}

def string_type_flow(fn,guard,var):
    # Exact str domain of the frozen entry; reject arbitrary callbacks/coercions.
    strings={a.arg for a in fn.args.args+fn.args.kwonlyargs}
    def typed(n):
        if isinstance(n,ast.Constant):return type(n.value) is str
        if isinstance(n,ast.Name):return n.id in strings
        if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Add):return typed(n.left) and typed(n.right)
        if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Slice):return typed(n.value) and all(x is None or isinstance(x,ast.Constant) and type(x.value) is int or isinstance(x,ast.UnaryOp) and isinstance(x.op,ast.USub) and isinstance(x.operand,ast.Constant) and type(x.operand.value) is int for x in [n.slice.lower,n.slice.upper,n.slice.step])
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='get' and isinstance(n.func.value,ast.Attribute) and isinstance(n.func.value.value,ast.Name) and n.func.value.value.id=='request' and n.func.value.attr in {'args','values','cookies','form'}:
            return len(n.args)==2 and all(isinstance(x,ast.Constant) and type(x.value) is str for x in n.args) and not n.keywords
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='urllib.parse.unquote_plus':return len(n.args)==1 and typed(n.args[0]) and not n.keywords
        return False
    for n in fn.body:
        if n is guard:return var in strings
        if isinstance(n,ast.Import) and all(a.name in {'urllib.parse','configparser'} for a in n.names):continue
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            if typed(n.value):strings.add(n.targets[0].id)
            else:strings.discard(n.targets[0].id)
            continue
        if isinstance(n,ast.AugAssign) and isinstance(n.target,ast.Name) and isinstance(n.op,ast.Add) and n.target.id in strings and typed(n.value):continue
        return False
    return False

def exclusion_proof(source,line):
 if not passive_source(source):return None
 tree=ast.parse(source)
 for fn in ast.walk(tree):
  if not isinstance(fn,ast.FunctionDef):continue
  for idx,guard in enumerate(fn.body[:-1]):
   if not isinstance(guard,ast.If) or guard.orelse:continue
   following=fn.body[idx+1];stmt=following.body[0] if isinstance(following,ast.Try) and following.body else following
   call=next((n for n in ast.walk(stmt) if isinstance(n,ast.Call) and n.lineno==line and isinstance(n.func,ast.Name) and n.func.id in {'eval','exec'}),None)
   if call is None or len(call.args)!=1 or call.keywords or not isinstance(call.args[0],ast.Name):continue
   var=call.args[0].id
   if not string_type_flow(fn,guard,var):continue
   if any(isinstance(n,(ast.Global,ast.Nonlocal)) or isinstance(n,(ast.Yield,ast.YieldFrom,ast.Await)) for n in ast.walk(fn)):continue
   # Only one terminal dynamic call in this statement; no callback/side-effect before it.
   calls=[n for n in ast.walk(stmt) if isinstance(n,ast.Call)]
   if len(calls)!=1:continue
   if not guard.body or not isinstance(guard.body[-1],(ast.Return,ast.Raise)) or any(isinstance(n,(ast.Assign,ast.AugAssign,ast.NamedExpr)) and any(isinstance(x,ast.Name) and x.id==var and isinstance(x.ctx,ast.Store) for x in ast.walk(n)) for n in ast.walk(guard)):continue
   # Restrict rejection arm to literal error return or literal RESPONSE += error followed by return.
   exits=len(guard.body)==1 and isinstance(guard.body[0],ast.Return) and isinstance(guard.body[0].value,ast.Constant)
   exits=exits or (len(guard.body)==2 and isinstance(guard.body[0],ast.AugAssign) and isinstance(guard.body[0].target,ast.Name) and guard.body[0].target.id!=var and isinstance(guard.body[0].value,ast.Constant) and isinstance(guard.body[1],ast.Return) and isinstance(guard.body[1].value,ast.Name) and guard.body[1].value.id==guard.body[0].target.id)
   if not exits:continue
   # Name rebinding and globals are conservatively rejected, including nested bindings.
   if any(isinstance(n,ast.Name) and n.id in {'eval','exec','request'} and isinstance(n.ctx,(ast.Store,ast.Del)) for n in ast.walk(tree)):continue
   for n in ast.walk(fn):
    if getattr(n,'lineno',0)>guard.lineno and getattr(n,'lineno',0)<call.lineno and isinstance(n,ast.Name) and n.id==var and isinstance(n.ctx,(ast.Store,ast.Del)):break
   else:
    plain=ast.parse(f'not {var}.startswith("\\\'") or not {var}.endswith("\\\'") or "\\\'" in {var}[1:-1]',mode='eval').body
    if ast.dump(plain)==ast.dump(guard.test):return {'kind':'single-quoted-string','variable':var,'guardLine':guard.lineno,'sinkLine':line,'domain':'exact-str','scope':'code-injection-at-this-point-only'}
    test=guard.test
    if isinstance(test,ast.Compare) and isinstance(test.left,ast.Name) and test.left.id==var and len(test.ops)==1 and isinstance(test.ops[0],ast.NotIn) and len(test.comparators)==1 and isinstance(test.comparators[0],(ast.Tuple,ast.List)):
     values=test.comparators[0].elts
     if 0<len(values)<=16 and all(isinstance(v,ast.Constant) and literal_expression(v.value) for v in values):return {'kind':'finite-literal-set','variable':var,'values':[v.value for v in values],'guardLine':guard.lineno,'sinkLine':line,'domain':'exact-str','scope':'code-injection-at-this-point-only'}
 return None

def run_probe(request):
 """Only called in a disposable, non-root, network-none container by the controller."""
 root=Path(request['sourceRoot']);contract=validate_contract(request['contract']);point=request['point'];probe=request['probe'];events=[];out=sys.stdout;original_eval=builtins.eval;original_exec=builtins.exec
 sys.path.insert(0,request['dependencies']);sys.path.insert(0,str(root));source_path=root/contract['path']
 sources={n:(root/n).read_bytes() for n in request['files']}
 if any(sha256(raw).hexdigest()!=request['files'][n] for n,raw in sources.items()):raise ValueError('Probe source changed')
 if any(Path(n).parts[0].split('.')[0] in {'flask','werkzeug','jinja2','markupsafe','sys','builtins','dis','json'} for n in sources):return {'state':'unknown','reason':'dependency-shadowing'}
 if any(not passive_source(raw.decode()) for raw in sources.values()):return {'state':'unknown','reason':'unsupported-introspection-or-source'}
 instructions={};target=[];values=[];tampered=False
 def observe(code,offset,fn,arg):
  filename=code.co_filename
  if filename!=str(source_path) or not (fn is original_eval or fn is original_exec):return
  positions=instructions.setdefault(code,{i.offset:i.positions for i in dis.get_instructions(code)})
  p=positions.get(offset)
  if p is None:return
  span=point['call']
  if (p.lineno,p.col_offset,p.end_lineno,p.end_col_offset)!=(span['start']['line'],span['start']['col']-1,span['end']['line'],span['end']['col']-1):return
  kind='eval' if fn is original_eval else 'exec'
  if len(target)<16:target.append({'pointId':point['id'],'callee':kind,'exactStr':type(arg) is str,'argumentSha256':sha256(arg.encode()).hexdigest() if type(arg) is str else None,'containsProbe':type(arg) is str and probe in arg,'argument':arg[:4096] if type(arg) is str else None})
 def returned(code,offset,value):
  if code.co_filename=='<string>' and target and target[-1]['containsProbe'] and len(values)<16:
   frame=sys._getframe(1);parent=frame.f_back
   if parent is None or parent.f_code.co_filename!=str(source_path):return
   p=next((i.positions for i in dis.get_instructions(parent.f_code) if i.offset==parent.f_lasti),None)
   span=point['call']
   if p is None or (p.lineno,p.col_offset,p.end_lineno,p.end_col_offset)!=(span['start']['line'],span['start']['col']-1,span['end']['line'],span['end']['col']-1):return
   marker=frame.f_locals.get('__harness_probe__')
   values.append({'pointId':point['id'],'evalWitness':type(value) is str and value=='138','execWitness':type(marker) is int and marker==138})
 tool=3;sys.monitoring.use_tool_id(tool,'harness-execution-proof');sys.monitoring.register_callback(tool,sys.monitoring.events.CALL,observe);sys.monitoring.register_callback(tool,sys.monitoring.events.PY_RETURN,returned);sys.monitoring.set_events(tool,sys.monitoring.events.CALL|sys.monitoring.events.PY_RETURN)
 error=None
 try:
  with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
   scope={'__name__':'harness_target','__file__':str(source_path)};exec(compile(sources[contract['path']],str(source_path),'exec'),scope)
   e=contract['entry']
   if e['kind']=='function':scope[e['name']](**{e['parameter']:probe})
   else:
    from flask import Flask
    app=scope[e['app']] if e['factory'] is None else Flask('harness-test')
    if e['factory']=='init':scope['init'](app)
    for n,text in e['resources'].items():p=Path.cwd()/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    if e['resources']:
     from jinja2 import DictLoader
     app.jinja_loader=DictLoader({n.removeprefix('templates/'):text for n,text in e['resources'].items() if n.startswith('templates/')})
    app.config.update(TESTING=True)
    client=app.test_client();kwargs={}
    if e['input']=='cookie':
     from urllib.parse import quote_plus
     client.set_cookie(e['key'],quote_plus(probe))
    elif e['input']=='query':kwargs['query_string']={e['key']:probe}
    else:kwargs['data']={e['key']:probe}
    client.open(e['path'],method=e['method'],**kwargs)
 except BaseException as exc:error=type(exc).__name__
 finally:
  tampered=sys.monitoring.get_events(tool)!=(sys.monitoring.events.CALL|sys.monitoring.events.PY_RETURN) or builtins.eval is not original_eval or builtins.exec is not original_exec
  sys.monitoring.set_events(tool,0);sys.monitoring.free_tool_id(tool)
 return {'state':'unknown' if tampered else 'observed','reason':'observer-changed' if tampered else error,'calls':target,'returns':values}

def verification_report(root,request):
 if sys.platform!='linux' or os.geteuid()==0 or sys.version_info[:2]!=(3,12):raise ValueError('Pinned non-root CPython3.12 VM required')
 root=Path(root);sys.path.insert(0,str(root/'code'))
 from eval_evidence_batch import location_inventory
 manifest=request['manifest'];sources={n:(root/'sources'/n).read_bytes().decode('utf-8') for n in manifest['files']}
 if any(sha256(v.encode()).hexdigest()!=manifest['files'][n] for n,v in sources.items()):raise ValueError('Verification source mismatch')
 inventory=location_inventory(sources)
 if inventory!=manifest['locationBinding']['inventory']:raise ValueError('Frozen locations changed')
 contract=validate_contract(request['contract']);point=request['point'];entry=inventory['files'].get(contract['path']);matches=[p for p in entry['points'] if p['id']==point['id']] if entry else []
 if matches!=[point]:raise ValueError('Point identity mismatch')
 start=time.monotonic();runs=[]
 for index,probe in enumerate(PROBES):
  if time.monotonic()-start>24:break
  work=Path('/tmp')/('probe-'+str(index));work.mkdir(mode=0o700)
  child={**request,'sourceRoot':str(root/'sources'),'files':manifest['files'],'probe':probe,'dependencies':str(root/'dependencies')}
  try:
   def limits():resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))
   with (work/'trace.json').open('wb') as output:
    result=subprocess.run([sys.executable,'-I','-B','-S',__file__,'--probe'],input=json.dumps(child).encode(),stdout=output,stderr=subprocess.DEVNULL,cwd=work,timeout=5,preexec_fn=limits)
   with (work/'trace.json').open('rb') as output:raw=output.read(32769)
   value=json.loads(raw) if result.returncode==0 and len(raw)<=32768 else {'state':'unknown','reason':'probe-failed-or-output-limit'}
  except subprocess.TimeoutExpired:value={'state':'unknown','reason':'probe-timeout'}
  runs.append({'probeSha256':sha256(probe.encode()).hexdigest(),'inputIndex':index,'trace':value})
 calls=[c for r in runs for c in r['trace'].get('calls',[])];source=sources[contract['path']];proof=exclusion_proof(source,point['call']['start']['line']);decision='unknown';reason='conditions-unresolved'
 if len(runs)==4 and all(r['trace']['state']=='observed' for r in runs) and calls:
  confirmed=any(any(c.get('containsProbe') and c.get('exactStr') for c in r['trace'].get('calls',[])) and any(v.get('evalWitness') or v.get('execWitness') for v in r['trace'].get('returns',[])) for r in runs)
  if confirmed:decision='confirmed';reason='untrusted-data-executed-at-point'
  elif proof and all(c['exactStr'] for c in calls):
   # Proof must cover every value reaching this point, not merely the four probes.
   if proof['kind']=='single-quoted-string' and all(c['argument'].startswith("'") and c['argument'].endswith("'") and "'" not in c['argument'][1:-1] for c in calls):decision='excluded';reason='supported-complete-string-constraint'
   elif proof['kind']=='finite-literal-set' and all(c['argument'] in proof['values'] for c in calls):decision='excluded';reason='supported-complete-finite-constraint'
 return {'version':1,'operation':'verify-execution','decision':decision,'reason':reason,'sourceSha256':point['sourceSha256'],'pointId':point['id'],'point':point,'contractSha256':digest(contract),'runs':runs,'proof':proof,'runtimePython':sys.version.split()[0],'probePolicySha256':digest({'policy':POLICY,'probes':PROBES}),'scope':'conditional code-injection proof at frozen point; no whole-project safety or anti-tamper attestation'}

if __name__=='__main__':
 if sys.argv[1:] == ['--probe']:
  raw=sys.stdin.buffer.read(2*1024*1024+1)
  if len(raw)>2*1024*1024:raise ValueError('Probe request limit')
  result=run_probe(json.loads(raw));print(json.dumps(result));raise SystemExit
 root=Path(sys.argv[1]);request=json.loads((root/'verification.json').read_bytes());print(json.dumps(verification_report(root,request)))
