"""Independent scratch-only publication integration. Fabricated captures, zero target execution."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,tempfile,copy,traceback,os,stat
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('roundtrip_fixture',R/'checks/full20_archive_fixture.py');v=load('roundtrip_verifier',R/'operator/verify_delivery.py');g=load('roundtrip_real_finalizer',R/'candidate/checks/finalize_closure.py');b=load('roundtrip_bounded',R/'operator/bounded.py')
tmp=Path(tempfile.mkdtemp(prefix='publication-roundtrip-',dir=R/'checks'));root=tmp/'guest';root.mkdir();blobs,expected,final=f.make();oldroot=expected['guestRoot'];expected['guestRoot']=str(root);frozen=set(expected['files']);generated={}
BASE_PREFIX='candidate/checks/evidence-runs/'
for name,body in blobs.items():
 if name in ['candidate/checks-evidence-index.json','candidate/proof.json','candidate/REPORT.md','candidate/phase-result.json','candidate/closure-manifest.json'] or name.startswith('candidate/evidence/'):continue
 if name not in frozen and name.endswith('.json'):
  try:body=(json.dumps(json.loads(body.decode().replace(oldroot,str(root))),sort_keys=True,indent=1)+'\n').encode()
  except Exception:pass
 if name.startswith(BASE_PREFIX) and name.endswith('/run.json'):
  doc=json.loads(body);doc.update(cwd=str(root/'candidate'),sourceRoot=str(root/'candidate'));body=(json.dumps(doc,sort_keys=True,indent=1)+'\n').encode()
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
result={'kind':'real-publication-entry-roundtrip','unitOnly':True,'fabricatedCaptures':True,'targetExecutions':0,'VMGroupsExecuted':0,'scratch':str(root),'runtimeSourceChanged':False}
try:
 captures=[str(root/(f.BASE+'/raw/'+s+'/run.json')) for s in final['attemptedSuites']]
 index=g.build_evidence_index(root/'candidate',captures,root/'candidate/checks-evidence-index.json');result['index']=index
 proof=g.build_proof(root/'candidate',root/'candidate/checks-evidence-index.json',root/'candidate/proof.json');result['proof']={k:x for k,x in proof.items() if k!='verified'}
 phase={'kind':'full20-linux-regression-phase','version':1,'state':'pending-independent-review','sourceManifestSha256':expected['sourceManifestSha256'],'expectedGroups':20,'completedGroups':20,'attemptedSuites':final['attemptedSuites'],'resourceQuiescent':True,'sourceUnchanged':True,'formalTargets':'0/16','r3':'blocked'};b.write_json(root/'candidate/phase-result.json',phase)
 gate=g.run_gate(root/'candidate',root/'candidate/checks-evidence-index.json',root/'candidate/proof.json',root/'candidate/phase-result.json',root/'candidate/REPORT.md',root/'candidate/closure-manifest.json');result['gate']=gate
 if gate.get('state')!='pending-independent-review' or gate.get('archiveCalls')!=0:raise ValueError('actual-gate-not-ready:'+str(gate.get('failedStage'))+':'+str(gate.get('detail')))
 final=json.loads(json.dumps(final).replace(oldroot,str(root)))
 for group in final['groups']:
  group['captureSha256']=sha256(Path(group['capture']).read_bytes()).hexdigest()
 final['publication']={'index':index,'proof':{'ok':proof['ok'],'sha256':proof['sha256']},'gate':gate,'operatorArchivePending':True};(root/'final.json').write_bytes(f.j(final))
 actual={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()};delivery,raw=f.pack(actual,expected,final);accepted=v.verify_bundle(delivery,raw,expected);result['hostAcceptance']=accepted;result['ok']=accepted.get('allPassed') is True
except Exception as error:
 result.update(ok=False,errorType=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
result['sources']={str(p.relative_to(R)):sha256(p.read_bytes()).hexdigest() for p in [R/'operator/verify_delivery.py',R/'candidate/checks/finalize_closure.py',R/'operator/bounded.py']}
with (R/'evidence/real-publication-roundtrip-qualified.json').open('x') as out:json.dump(result,out,indent=2,default=str);out.write('\n')
print(json.dumps({k:result.get(k) for k in ['ok','reason','scratch','hostAcceptance']}))
