"""Pinned upstream component probe, executed only inside the isolated VM container."""
from pathlib import Path
import ast,hashlib,importlib.metadata,json,os,re,signal,sys
from fractions import Fraction
signal.alarm(20)
assert os.geteuid()==65534 and Path('/.dockerenv').is_file() and sys.flags.isolated and sys.flags.no_site
assert sys.version.split()[0]=='3.12.15'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads(Path('/protocol.json').read_text());assert sha('/probe.py')==plan['probeSha256']
for n,h in plan['inputs'].items():assert sha(n)==h
entries={str(p.relative_to('/deps')):sha(p) for p in Path('/deps').rglob('*') if p.is_file()};assert hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()==plan['dependencyTreeSha256']
status=dict(row.split(':',1) for row in Path('/proc/self/status').read_text().splitlines() if ':' in row)
assert status['CapEff'].strip()=='0000000000000000' and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456' and Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert set(os.listdir('/sys/class/net'))=={'lo'} and not Path('/var/run/docker.sock').exists()
write_errnos={}
for name in ['/src','/deps','/']:
 try:Path(name,'ORACLE_READONLY_TEST').write_text('x');raise AssertionError('read-only protection failed')
 except OSError as e:write_errnos[name]=e.errno
assert set(write_errnos.values())=={30}
sys.path.insert(0,'/deps')
import numpy as np
import sympy
from sympy import Matrix
from sympy.parsing.sympy_parser import parse_expr
import mpmath
assert np.__version__=='1.26.4' and sympy.__version__=='1.12' and mpmath.__version__=='1.3.0'
assert all(Path(v.__file__).is_relative_to('/deps') for v in [np,sympy,mpmath])
observations=[]
for variant in ['vulnerable','patched']:
 path=Path('/src')/(variant+'.py');raw=path.read_bytes();tree=ast.parse(raw,filename=str(path));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JonesFaithfulTransformation')
 assert hashlib.sha256(ast.dump(cls,include_attributes=True).encode()).hexdigest()==plan['classes'][variant]
 # Preserve the original whole class AST/line locations; upstream imports and unrelated package entrypoints are outside this component experiment.
 future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0);ast.copy_location(future,tree.body[0]);module=ast.fix_missing_locations(ast.Module(body=[future,cls],type_ignores=[]))
 ns={'__name__':'component_'+variant,'__file__':str(path),'np':np,'Matrix':Matrix,'parse_expr':parse_expr,'Fraction':Fraction,'re':re}
 exec(compile(module,str(path),'exec'),ns)
 for vector in plan['vectors']:
  eval_frames=[];sum_calls=[]
  def trace(frame,event,arg):
   if event=='call' and frame.f_code.co_filename=='<string>' and frame.f_back and frame.f_back.f_code.co_filename==str(path):
    assert len(eval_frames)<16
    eval_frames.append({'parentFile':frame.f_back.f_code.co_filename,'parentLine':frame.f_back.f_lineno,'parentFunction':frame.f_back.f_code.co_name,'compiledNames':list(frame.f_code.co_names),'builtinsDisabled':frame.f_globals.get('__builtins__') is None})
   return trace
  def profile(frame,event,arg):
   if event=='c_call' and getattr(arg,'__name__',None)=='sum' and getattr(arg,'__module__',None)=='builtins' and frame.f_code.co_filename=='<string>':
    assert len(sum_calls)<4
    sum_calls.append({'callerFile':frame.f_code.co_filename,'compiledNames':list(frame.f_code.co_names),'builtinsDisabled':frame.f_globals.get('__builtins__') is None})
  error=None;value=None
  sys.settrace(trace);sys.setprofile(profile)
  try:
   P,p=ns['JonesFaithfulTransformation'].parse_transformation_string(vector['input']);value={'P':np.asarray(P,dtype=float).tolist(),'p':list(p)}
  except ValueError:error='ValueError'
  finally:sys.setprofile(None);sys.settrace(None)
  if vector['kind']=='normal':
   assert error is None and np.allclose(value['P'],vector['expected']['P']) and np.allclose(value['p'],vector['expected']['p']) and not sum_calls
  elif variant=='vulnerable':
   marker=vector['marker'];assert error is None and value['P']==[[1.0,0.0,float(marker)],[0.0,1.0,float(marker)],[0.0,0.0,float(marker+1)]] and value['p']==[0.0,0.0,0.0]
   assert len(sum_calls)==1 and sum_calls[0]['builtinsDisabled'] and any(v['parentLine']==plan['sinkLine'] and v['parentFunction']=='<listcomp>' and v['builtinsDisabled'] for v in eval_frames)
  else:assert error=='ValueError' and not sum_calls
  observations.append({'variant':variant,'id':vector['id'],'kind':vector['kind'],'inputSha256':hashlib.sha256(vector['input'].encode()).hexdigest(),'result':value,'error':error,'evalFrames':eval_frames,'builtinSumCalls':sum_calls,'countsTowardQualificationMinima':False})
print(json.dumps({'ok':True,'probeSha256':sha('/probe.py'),'protocolSha256':sha('/protocol.json'),'sourceSha256':{v:sha('/src/'+v+'.py') for v in ['vulnerable','patched']},'dependencies':{k:{'version':v.__version__,'file':v.__file__} for k,v in [('numpy',np),('sympy',sympy),('mpmath',mpmath)]},'writeFailureErrnos':write_errnos,'observations':observations,'scope':'unchanged original class AST, explicit dependency globals; parse_transformation_string only; not full pymatgen installation or CIF parser path','r3Qualified':False}))
