"""Unit-only fabricated evidence contract; no target, Docker, VM or BPF execution."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,io,zipfile,copy
R=Path(__file__).resolve().parents[1]
BASE='candidate/checks/evidence-runs/full20-linux-20261123'
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def j(v):return (json.dumps(v,sort_keys=True,indent=1)+'\n').encode()
def h(b):return sha256(b).hexdigest()
def make():
 c=load('fixture_consumer',R/'operator/consumer_vm.py');g=load('fixture_finalizer',R/'candidate/checks/finalize_closure.py');b=load('fixture_batch',R/'operator/full20_batch.py')
 source=g._source_state(R/'candidate');plan=json.loads((R/'operator/suite-plan.json').read_bytes());root=str(c.GUEST)
 names={'candidate/'+n for n in source['files']}|{'candidate/protocol-manifest.json'}
 baseline=json.loads((R/'candidate/baseline/protocol-manifest.json').read_bytes());names|={'candidate/baseline/'+n for n in baseline['files']}|{'candidate/baseline/protocol-manifest.json'}|set(c.OPERATOR_FILES)|set(c.EXTRA_FILES)
 blobs={n:(R/n).read_bytes() for n in names};frozen={n:{'bytes':len(v),'sha256':h(v)} for n,v in blobs.items()};hashmap={n:v['sha256'] for n,v in frozen.items()}
 expected={'full20':True,'guestRoot':root,'sourceManifestSha256':source['manifestSha256'],'caseIds':list(c.CONSUMER_CASE_IDS),'files':frozen}
 rows=[];groups=[];entries=[];captures=[];maps=[];count=0;commands={}
 snapshot={'entries':source['actual'],'ok':True,'manifestSha256':source['manifestSha256'],'fileCount':92,'declaredCount':92,'problems':[],'sourceRoot':root+'/candidate'}
 oldexe=b.sys.executable;b.sys.executable='/usr/bin/python3'
 try:
  for suite in plan['order']:commands[suite]=b._command(plan,suite,Path(root))
 finally:b.sys.executable=oldexe
 for index,suite in enumerate(plan['order']):
  n=g._FIXED_COUNTS[suite];producer=commands[suite];resname=plan['suites'][suite]['resultName'];resultrel=BASE+'/'+resname;rawdir=BASE+'/raw/'+suite;capture=rawdir+'/run.json';captures.append(root+'/'+capture)
  if suite=='baseline-verify':result={'fileCount':87,'recomputed':87,'mismatched':[],'manifestSha256':g._BASELINE_MANIFEST_SHA256};validcount=1
  elif suite=='independent-116':
   result={'allPassed':True,'passed':n,'total':n,'candidateManifestSha256':source['manifestSha256'],'checks':[{'id':f'unit-{suite}-{i}','passed':True} for i in range(n)],'components':[{'script':k,'scriptSha256':v[0],'exitCode':0,'passed':v[1],'total':v[1]} for k,v in g._INDEPENDENT_COMPONENTS.items()]};validcount=n
  else:
   result={'passed':n,'total':n,'results':[{'id':f'unit-{suite}-{i}','suite':suite,'passed':True} for i in range(n)],'failed':[]};validcount=n
   if suite=='pure-compile':
    for row,name in zip(result['results'],sorted(g._compile_source_files(source['files']))):row['file']=name;row['id']=name
   if suite=='consumer-12':
    old=R.parent/'harness-linux-consumer-capacity-20261123/evidence/VM-original-evidence.zip'
    with zipfile.ZipFile(old) as z:result=json.loads(z.read('evidence/consumer-12/results.json'))
  count+=validcount;rb=j(result);blobs[resultrel]=rb
  raw={'suite':suite,'command':producer,'returncode':0,'sourceClosureOk':True,'sourceUnchanged':True,'sourceManifestBefore':snapshot,'sourceManifestAfter':snapshot,'resultFile':root+'/'+resultrel,'resultSha256':h(rb),'resultPassed':result.get('passed'),'resultTotal':result.get('total'),'stdoutFile':'stdout.bin','stdoutSha256':h(b''),'stdoutBytes':0,'stderrFile':'stderr.bin','stderrSha256':h(b''),'stderrBytes':0,'simulated':True,'unitOnly':True}
  blobs[capture]=j(raw);blobs[rawdir+'/stdout.bin']=b'';blobs[rawdir+'/stderr.bin']=b'';blobs[rawdir+'/returncode.txt']=b'0\n';blobs[rawdir+'/source-before.json']=j(snapshot);blobs[rawdir+'/source-after.json']=j(snapshot)
  wrapper=['/usr/bin/python3','-I','-B',root+'/candidate/checks/evidence_capture.py','--suite',suite,'--source-root',root+'/candidate','--run-dir',root+'/'+rawdir,'--result',root+'/'+resultrel,'--timeout','100','--',*producer]
  pid=2100000000+index;identity={'pid':pid,'pgid':pid,'groupLeader':True,'starttime':1,'bootId':'00000000-0000-0000-0000-000000000001'}
  row={'suite':suite,'passed':True,'returncode':0,'problem':None,'cleanupConfirmed':True,'pid':pid,'sourceAndScriptsBefore':hashmap,'sourceAndScriptsAfter':hashmap,'capacitySamples':2,'peakTreeBytes':8000000,'minFreeBytes':1000000000,'immutableFilesUnchanged':True,'outputBytes':{'stdout':0,'stderr':0},'command':wrapper,'cwd':root+'/candidate','unitOnly':True};rows.append(row)
  blobs['evidence/'+suite+'/intent.json']=j({'suite':suite,'identityRequired':True,'createdBeforeProcess':True,'cwd':root+'/candidate','command':wrapper})
  blobs['evidence/'+suite+'/process.json']=j({'pid':pid,'processGroup':pid,'originalPopenChild':True,'identity':identity})
  blobs['evidence/'+suite+'/capture.json']=j(row);blobs['evidence/'+suite+'/stdout.bin']=b'';blobs['evidence/'+suite+'/stderr.bin']=b''
  entries.append({'suite':suite,'command':producer,'captureFile':capture[len('candidate/'):],'captureSha256':h(blobs[capture]),'resultFile':resultrel[len('candidate/'):],'resultSha256':h(rb)})
  groups.append({'suite':suite,'command':producer,'result':root+'/'+resultrel,'capture':root+'/'+capture,'sourceBefore':source['manifestSha256'],'sourceAfter':source['manifestSha256'],'validationCounts':[validcount,validcount],'captureSha256':h(blobs[capture])})
  for role,path,name in [('capture',capture,'capture.json'),('result',resultrel,'result.json'),('stdout',rawdir+'/stdout.bin','stdout.bin'),('stderr',rawdir+'/stderr.bin','stderr.bin'),('returncode',rawdir+'/returncode.txt','returncode.txt')]:
   archive='evidence/'+suite+'/'+name;blobs['candidate/'+archive]=blobs[path];maps.append({'suite':suite,'role':role,'relativePath':path[len('candidate/'):],'sourcePath':root+'/'+path,'archivePath':archive,'sha256':h(blobs[path]),'bytes':len(blobs[path]),'identity':[1,len(maps)+1]})
 # Reuse old receipt bytes as unit shape input only; all these are synthetic verifier fixtures.
 with zipfile.ZipFile(R.parent/'harness-linux-consumer-capacity-20261123/evidence/VM-original-evidence.zip') as z:
  oldfinal=json.loads(z.read('final.json'));inner=oldfinal['inner']
  for name in z.namelist():
   if name.startswith('candidate/'+inner['box']+'/'):blobs[name]=z.read(name)
 indexdoc={'kind':g.INDEX_KIND,'version':1,'state':'completed','entries':entries,'sourceManifest':{'path':'protocol-manifest.json','sha256':source['manifestSha256'],'fileCount':92,'entries':source['actual']},'checks':{'sourceUnchanged':True,'allReturncodesZero':True,'allResultsPassed':True}}
 blobs['candidate/checks-evidence-index.json']=j(indexdoc);idx=h(blobs['candidate/checks-evidence-index.json'])
 proof={'kind':g.PROOF_KIND,'version':1,'state':'verified','decision':'pass','verdict':'pass','sourceRoot':root+'/candidate','sourceManifestSha256':source['manifestSha256'],'sourceFileCount':92,'evidenceIndexSha256':idx,'entryCount':20,'passed':count,'total':count,'checks':{'sourceManifest':True,'evidenceIndex':True,'rawMembers':True,'derivedDecision':'pass'},'targetExecutions':0,'realContainers':0,'realBpftrace':0,'formalTargets':'0/16','r3':'blocked'}
 blobs['candidate/proof.json']=j(proof);ph=h(blobs['candidate/proof.json']);blobs['candidate/REPORT.md']=b'Unit-only full20 evidence format test. No VM test executed.\n'
 phase={'kind':'full20-linux-regression-phase','version':1,'state':'pending-independent-review','sourceManifestSha256':source['manifestSha256'],'expectedGroups':20,'completedGroups':20,'attemptedSuites':plan['order'],'resourceQuiescent':True,'sourceUnchanged':True,'formalTargets':'0/16','r3':'blocked'};blobs['candidate/phase-result.json']=j(phase)
 closurefiles={n:h(v) for n,v in blobs.items() if n in {'candidate/'+x for x in source['files']} or n in {'candidate/protocol-manifest.json','candidate/REPORT.md','candidate/phase-result.json','candidate/checks-evidence-index.json','candidate/proof.json'} or n.startswith('candidate/evidence/')}
 closurefiles={n[len('candidate/'):]:v for n,v in closurefiles.items()}
 closure={'kind':'consumer-closure-input-manifest','version':1,'state':'pending-independent-review','sourceRoot':root+'/candidate','sourceManifestSha256':source['manifestSha256'],'selfExcluded':True,'files':closurefiles,'fileCount':len(closurefiles),'requiredClosureMembers':['REPORT.md','phase-result.json','checks-evidence-index.json','proof.json'],'validatedArtifactMap':maps,'validatedArtifactCount':100}
 blobs['candidate/closure-manifest.json']=j(closure);ch=h(blobs['candidate/closure-manifest.json'])
 pub={'index':{'ok':True,'sha256':idx,'entries':20},'proof':{'ok':True,'sha256':ph},'gate':{'state':'pending-independent-review','archiveCalls':0,'closureManifest':{'ok':True,'sha256':ch},'report':{'sha256':h(blobs['candidate/REPORT.md'])},'proof':{'ok':True,'proofSha256':ph,'evidenceIndexSha256':idx,'sourceManifestSha256':source['manifestSha256'],'passed':count,'total':count}},'operatorArchivePending':True}
 final={'kind':'full20-linux-controller-final','full20':True,'expectedGroups':20,'batchState':'pending-final-review','complete':True,'suitePassed':True,'targetChecksAllTrue':True,'outerGroupExited':True,'innerCleanupConfirmed':True,'sourceUnchanged':True,'budgetOk':True,'unexpectedResourceCallLogEmpty':True,'actualProcessQuiescent':True,'sourceManifestSha256':source['manifestSha256'],'attemptedSuites':plan['order'],'rows':rows,'groups':groups,'captures':captures,'inner':inner,'publication':pub,'failedGroup':None,'unitOnly':True}
 blobs['final.json']=j(final);blobs['staging-verified.json']=j({'files':hashmap});blobs['evidence/unexpected-resource-calls.log']=b''
 return blobs,expected,final

def pack(blobs,expected,final):
 members={n:{'sha256':h(v),'bytes':len(v)} for n,v in blobs.items()};out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for n,v in blobs.items():z.writestr(n,v)
  z.writestr('LINKS.json','{}');z.writestr('ARCHIVE-ISSUES.json','[]')
 raw=out.getvalue();delivery={'archiveComplete':True,'controllerFinalWritten':True,'collectionIssues':[],'guestRoot':expected['guestRoot'],'archiveSha256':h(raw),'members':members,'linksRecordedNotFollowed':{},'result':final,'unitOnly':True}
 return delivery,raw
