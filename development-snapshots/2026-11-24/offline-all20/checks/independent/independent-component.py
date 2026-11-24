"""Independent pure/CLI checks: never spawn Docker, BPF or a target."""
from pathlib import Path
from hashlib import sha256
import copy,inspect,json,subprocess,sys,tempfile,traceback
P=Path(sys.argv[1]).resolve();R=Path(__file__).resolve().parent;PROJECT=Path(sys.argv[2]) if len(sys.argv)>2 else None;OLD=PROJECT/'stdlib-cli-record-validation' if PROJECT else R.parent/'harness-stdlib-cli-record-validation-20261115/prepared';sys.path.insert(0,str(P/'tools'))
import buffer_protocol_v2 as parser,judge,structure
checks=[]
def must(v,m='assertion'):assert v,m
def check(n,f):
 try:d=f();checks.append({'name':n,'passed':True,'detail':d})
 except Exception as e:checks.append({'name':n,'passed':False,'error':type(e).__name__+':'+str(e),'traceback':traceback.format_exc()[-1700:]})
def hashes():
 m=json.loads((P/'protocol-manifest.json').read_bytes());rows=[]
 for n,h in m['files'].items():must(sha256((P/n).read_bytes()).hexdigest()==h,n);rows.append({'path':n,'sha256':h})
 return rows
check('actual-source-manifest',hashes)
protected=['tools/buffer_protocol.py','tools/buffer_protocol_v2.py','tools/observer_template.bt','tools/observer_template_buffer.bt','tools/observer_template_buffer_v2.bt','tools/observation_pure.py','tools/observer_render.py','tools/structure.py','tools/target_launcher.py','tools/experiment_compile.py','tools/preflight_selfcheck.py','tools/zero_target_preflight.py','tools/preflight_verify.py','tools/observer-profile.lock.json','experiment-plan.json','fixtures/echo/sce_echo_sink.py','fixtures/safe-quoting/sce_quoted_sink.py','fixtures/structure-controlled/sce_raw_sink.py','fixtures/wrong-function/sce_two_sites.py']
for n in protected:check('protected:'+n,lambda n=n:must((P/n).read_bytes()==(OLD/n).read_bytes(),n))
raw=(P/'proof/observer.raw').read_bytes();cfg=json.loads((P/'proof/preflight-config.json').read_bytes());pid=json.loads((P/'proof/container-pid.json').read_bytes())['targetPid'];args=('preflight','66e7bbb39ef1553b',cfg['callerPath'],cfg['callOffset'],pid,65534);obs=parser.parse_receipt(raw,*args,require_events=1);must(obs['state']=='complete');ev=obs['events'][0]
def raw_case(data,good):
 v=parser.parse_receipt(data,*args,require_events=1);must((v['state']=='complete')==good,str(v['errors']));must(v['rawSha256']==sha256(data).hexdigest());return v['errors']
check('historical-whole-raw',lambda:raw_case(raw,True))
for n in [0,8,9]:check('framing-extra:'+str(n),lambda n=n:raw_case(raw[:-3]+b'\n'*n,n<=8))
for n,b in [('no-END',raw[:raw.index(b'END ')]),('internal-blank',raw.replace(b'DCODE 0',b'\nDCODE 0',1)),('tail-text',raw+b'x\n')]:check('raw-reject:'+n,lambda b=b:raw_case(b,False))
result={'callerSha256':ev['callerSha256'],'callerCandidates':[{'qualname':'_run','firstlineno':168,'callerSha256':ev['callerSha256']}]}
expected={'payloadRole':'computation','payloadSyntax':'valid','syntaxRejectExpected':False,'expectedComputation':{'structureSha256':ev['dynamicStructureSha256'],'codeSha256':ev['dynamicCodeSha256']},'dataBaseline':None}
def derive(name,events,res,ex,code,decision,reason):
 v=judge.derive_verdict(events,res,ex,{},code);must(v['decision']==decision and v['reason']==reason,str(v));return v
check('derive-confirmed-from-recomputed-event',lambda:derive('',obs['events'],result,expected,0,'confirmed','structure-match'))
data=copy.deepcopy(expected);data['expectedComputation']=None;data['dataBaseline']={'structureSha256':ev['dynamicStructureSha256']}
check('derive-data-only',lambda:derive('',obs['events'],result,data,0,'excluded','data-only-structure'))
check('derive-echo-zero',lambda:derive('',[],result,{'payloadRole':'echo'},0,'excluded','no-dynamic-event'))
other=copy.deepcopy(result);other['callerSha256']='a'*64
check('derive-wrong-function',lambda:derive('',obs['events'],other,expected,0,'excluded','caller-identity-mismatch'))
q4={'payloadRole':'data','payloadSyntax':'syntax-error','syntaxRejectExpected':True,'dataBaseline':None}
check('q4-valid-syntax-reject',lambda:derive('',[],result,q4,3,'excluded','syntax-reject'))
for code in [0,None,True]:check('q4-wrong-exit:'+str(code),lambda code=code:derive('',[],result,q4,code,'unknown','syntax-reject-target-exit'))
check('q4-events-not-exclusion',lambda:derive('',obs['events'],result,q4,3,'unknown','syntax-reject-with-events'))
payload='q"x';valid={'state':'prepared','targetExecuted':False,'payloadRole':'data','payload':payload,'payloadSha256':sha256(payload.encode()).hexdigest(),'payloadSyntax':'syntax-error','syntaxRejectExpected':True,'dataBaseline':None,'expectedComputation':None}
check('expected-valid-q4',lambda:must(judge.verify_expected(valid) is None))
for label,value in [('None',None),('list',[]),('number',12),('boolean',True)]:
 def malformed(value=value):
  v=copy.deepcopy(valid);v['payload']=value;reason=judge.verify_expected(v);must(type(reason) is str and reason);return reason
 check('expected-bad-payload:'+label,malformed)
with tempfile.TemporaryDirectory(prefix='formal-independent-') as td:
 t=Path(td);inputs={k:t/(k+'.json') for k in ['binding','expected','observation','attempt','admission','layout','review-receipt']}
 for k,p in inputs.items():p.write_text('{}')
 rawp=t/'observer.raw';rawp.write_bytes(raw);obp=t/'observer.bt';obp.write_text('SIMULATED malformed evidence test; never executed')
 for key in ['binding','expected','observation','attempt','admission','layout']:
  for typ,value in [('null',None),('list',[]),('text','invalid')]:
   def run(key=key,typ=typ,value=value):
    for k,p in inputs.items():p.write_text(json.dumps(value if k==key else {}))
    out=t/(key+'-'+typ+'-result.json');argv=[sys.executable,'-I','-B',str(P/'tools/judge.py')]
    for k in ['binding','expected','observation','attempt','admission','layout','review-receipt']:argv+=['--'+k,str(inputs[k])]
    argv+=['--manifest',str(P/'protocol-manifest.json'),'--preflight',str(t/'absent-receipt.json'),'--observer',str(obp),'--raw',str(rawp),'--template',str(P/'tools/observer_template_buffer_v2.bt'),'--profile',str(P/'tools/observer-profile.lock.json'),'--out',str(out)]
    v=subprocess.run(argv,capture_output=True,timeout=10);must(v.returncode==3 and out.is_file(),str((v.returncode,v.stderr[-400:])));d=json.loads(out.read_bytes());must(d['decision']=='unknown' and d['reason']);return d['reason']
   check('judge-malformed:'+key+':'+typ,run)
 for command in ['query','recover','cleanup']:
  for label,args2 in [('missing',[]),('both',['--attempt','1','--prepare-id','a'*32])]:
   def run(command=command,args2=args2):
    v=subprocess.run([sys.executable,'-I','-B',str(P/'tools/experiment_runner.py'),command,*args2],capture_output=True,timeout=10);must(v.returncode==2,str((v.returncode,v.stdout,v.stderr)));return {'exitCode':2}
   check('selector:'+command+':'+label,run)
out={'kind':'codex-independent-formal-admission-checks','candidateManifestSha256':sha256((P/'protocol-manifest.json').read_bytes()).hexdigest(),'allPassed':all(x['passed'] for x in checks),'passed':sum(x['passed'] for x in checks),'total':len(checks),'checks':checks,'selfchecks':0,'formalTargets':'0/16','r3':'blocked','scope':'Actual pure trusted modules and malformed-input CLI; historical raw only as diagnostic'}
print(json.dumps(out,indent=2));raise SystemExit(0 if out['allPassed'] else 1)
