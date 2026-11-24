"""Bounded CPython negative cases and separate authored positive controls; container only."""
from pathlib import Path
import errno,hashlib,importlib.util,io,json,os,runpy,sys
assert sys.platform=='linux' and os.geteuid()==65534 and Path('/.dockerenv').is_file()
plan=json.loads(Path('/protocol.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha('/probe.py')==plan['probeSha256']
for name,expected in plan['sources'].items():assert sha('/src/'+name)==expected
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert status['CapEff'].strip()=='0000000000000000' and status['NoNewPrivs'].strip()=='1' and status['Seccomp'].strip()=='2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='268435456' and Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert set(os.listdir('/sys/class/net'))=={'lo'}
assert all(not Path(p).exists() for p in ['/home/purge/.ssh','/home/purge/.dsh-improved','/var/run/docker.sock'])
for directory in ['/src','/']:
 try:Path(directory,'ORACLE_NO_WRITE').write_text('x');raise AssertionError('Input writable')
 except OSError as error:assert error.errno==errno.EROFS

def load(name,file):
 spec=importlib.util.spec_from_file_location(name,file);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

def observe(path,action):
 frames=[]
 def trace(frame,event,arg):
  caller=frame.f_back
  if event=='call' and frame.f_code.co_filename=='<string>' and caller and caller.f_code.co_filename==str(path):
   constants=[value for value in frame.f_code.co_consts if type(value) in [str,int,bool,type(None)]]
   nested=[{'name':value.co_name,'names':list(value.co_names),'variables':list(value.co_varnames)} for value in frame.f_code.co_consts if isinstance(value,type(frame.f_code))]
   frames.append({'line':caller.f_lineno,'function':caller.f_code.co_name,'names':list(frame.f_code.co_names),'constants':constants,'nestedCode':nested,'generatedCode':caller.f_locals.get('code'),'emptyBuiltins':caller.f_locals.get('namespace',{}).get('__builtins__')=={}})
  return trace
 sys.settrace(trace)
 try:
  try:result=action();error=None
  except (ValueError,SyntaxError) as exception:result=None;error=type(exception).__name__
 finally:sys.settrace(None)
 return result,error,frames

ast_path=Path('/src/stdlib_ast.py');collections_path=Path('/src/stdlib_collections.py')
ast_module=load('oracle_source_ast',ast_path);collections_module=load('oracle_source_collections',collections_path)
observations=[]
for item in plan['literalCases']:
 value=item['value'];assert type(value) is str and len(value)<=512
 result,error,frames=observe(ast_path,lambda:ast_module.literal_eval(value))
 assert not frames
 if item['accept']:assert error is None and repr(result)==item['expected']
 else:assert error in ['ValueError','SyntaxError']
 observations.append({'id':item['id'],'role':'independent-normal-path-witness','caseId':'cpython-literal-eval','countsTowardMinima':False,'accepted':error is None,'errorType':error,'resultRepresentation':repr(result) if error is None else None,'evalFrames':frames})
for item in plan['namedtupleCases']:
 assert type(item['typename']) is str and all(type(name) is str for name in item['fields'])
 def action():
  cls=collections_module.namedtuple(item['typename'],item['fields'],rename=item['rename'],module='oracle_fixture');instance=cls(11,22)
  return {'fields':list(instance._fields),'values':list(instance)}
 result,error,frames=observe(collections_path,action)
 if item['accept']:
  assert error is None and result=={'fields':item['expectedFields'],'values':[11,22]} and len(frames)==1
  frame=frames[0];assert frame['line']==plan['locations']['namedtupleEval'] and frame['function']=='namedtuple' and frame['emptyBuiltins']
  nested,=frame['nestedCode'];assert nested['name']=='<lambda>' and nested['names']==['_tuple_new'] and nested['variables']==['_cls',*item['expectedFields']]
  assert str(plan['marker']) not in frame['generatedCode'] and '17389' not in frame['generatedCode']
 else:assert error=='ValueError' and not frames
 observations.append({'id':item['id'],'role':'independent-normal-path-witness','caseId':'cpython-namedtuple','countsTowardMinima':False,'accepted':error is None,'errorType':error,'result':result,'evalFrames':frames})
for name in ['input_one.py','input_two.py']:
 path=Path('/src')/name;saved=sys.stdin;sys.stdin=io.StringIO(plan['expression']+'\n')
 try:result,error,frames=observe(path,lambda:runpy.run_path(str(path)))
 finally:sys.stdin=saved
 assert error is None and type(result['result']) is int and result['result']==plan['marker'] and len(frames)==1
 assert frames[0]['line']==2 and plan['marker'] in frames[0]['constants']
 observations.append({'id':name,'caseId':name,'role':'authored-positive-control','countsTowardMinima':False,'result':result['result'],'evalFrames':frames})
listeners=sum(1 for name in ['tcp','tcp6'] if (p:=Path('/proc/net')/name).exists() for line in p.read_text().splitlines()[1:] if line.split()[3]=='0A');assert listeners==0
print(json.dumps({'ok':True,'python':sys.version.split()[0],'probeSha256':sha('/probe.py'),'protocolSha256':sha('/protocol.json'),'sourceIdentityMatched':True,'conditions':{'uid':os.geteuid(),'networkInterfaces':['lo'],'tcpListenersAfter':listeners,'readonlyFailuresRequired':'EROFS','plainBuiltInStringsOnly':True,'noDoSOrCustomPythonObjectClaim':True},'observations':observations,'independentNegativeSourceCases':2,'authoredPositiveControls':2,'vectorsAreNotCaseCounts':True}))
