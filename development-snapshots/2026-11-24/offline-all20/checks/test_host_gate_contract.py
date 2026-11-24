from pathlib import Path
from hashlib import sha256
from unittest.mock import patch
import importlib.util,json,unittest,zipfile,io
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('host_gate_contract',R/'operator/verify_delivery.py')
g=load('host_gate_finalizer',R/'candidate/checks/finalize_closure.py')
b=load('host_gate_batch',R/'operator/full20_batch.py')
c=load('host_gate_consumer',R/'operator/consumer_vm.py')
cap=load('host_gate_capture',R/'candidate/checks/evidence_capture.py')
SOURCE=sha256((R/'candidate/protocol-manifest.json').read_bytes()).hexdigest()
PLAN=json.loads((R/'operator/suite-plan.json').read_bytes())
BASE='candidate/checks/evidence-runs/full20-linux-20261123'
class HostGateContract(unittest.TestCase):
 def setUp(self):
  self.source=g._source_state(R/'candidate');self.root=str(c.GUEST)
  names={'candidate/'+n for n in self.source['files']}|{'candidate/protocol-manifest.json'}
  baseline=json.loads((R/'candidate/baseline/protocol-manifest.json').read_bytes())
  names|={'candidate/baseline/'+n for n in baseline['files']}|{'candidate/baseline/protocol-manifest.json'}|set(c.OPERATOR_FILES)|set(c.EXTRA_FILES)
  self.frozen={n:{'sha256':sha256((R/n).read_bytes()).hexdigest(),'bytes':(R/n).stat().st_size} for n in names}
  self.expected={'full20':True,'guestRoot':self.root,'sourceManifestSha256':SOURCE,'files':self.frozen,'caseIds':list(c.CONSUMER_CASE_IDS)}
 def test_registry_real_signature(self):
  order,suites,digest=m._f20_registry(PLAN,self.expected,b);self.assertEqual(order,PLAN['order']);self.assertEqual(digest,SOURCE)
 def test_trusted_module_is_explicit_candidate_not_baseline(self):
  self.assertEqual(m._f20_expected_rel(self.frozen,'finalize_closure.py'),'candidate/checks/finalize_closure.py')
 def test_candidate_source_map_keeps_baseline_separate(self):
  source=m._f20_source(g,R,self.expected,self.frozen,SOURCE);self.assertEqual(source['actual'],self.source['actual'])
 def test_actual_capture_source_snapshot_shape(self):
  snapshot=cap.source_closure(R/'candidate');self.assertTrue(snapshot['ok']);self.assertTrue(m._f20_snapshot_ok(snapshot,self.source))
 def test_actual_registered_aux_path(self):
  with patch.object(b.sys,'executable','/usr/bin/python3'):want=b._command(PLAN,'independent-116',Path(self.root))
  self.assertEqual(m._f20_expand_command(PLAN['suites']['independent-116']['command'],self.expected,BASE),want)
 def test_actual_wrapper_argv_includes_capture_options(self):
  with patch.object(b.sys,'executable','/usr/bin/python3'):producer=b._command(PLAN,'consumer-12',Path(self.root))
  command=['/usr/bin/python3','-I','-B',self.root+'/candidate/checks/evidence_capture.py','--suite','consumer-12','--source-root',self.root+'/candidate','--run-dir',self.root+'/'+BASE+'/raw/consumer-12','--result',self.root+'/'+BASE+'/consumer-12.json','--timeout','100','--',*producer]
  m._f20_wrapper_command_ok(command,producer)
 def test_actual_proof_uses_case_sum_not_group_count(self):
  total=sum(1 if s=='baseline-verify' else g._FIXED_COUNTS[s] for s in PLAN['order'])
  proof={'kind':g.PROOF_KIND,'version':1,'state':'verified','decision':'pass','verdict':'pass','sourceRoot':self.root+'/candidate','sourceManifestSha256':SOURCE,'sourceFileCount':92,'evidenceIndexSha256':'a'*64,'entryCount':20,'passed':total,'total':total,'checks':{'sourceManifest':True,'evidenceIndex':True,'rawMembers':True,'derivedDecision':'pass'},'targetExecutions':0,'realContainers':0,'realBpftrace':0,'formalTargets':'0/16','r3':'blocked'}
  m._f20_proof({'candidate/proof.json':json.dumps(proof).encode()},self.expected,self.source,'a'*64)
 def test_actual_index_has_six_entry_fields(self):
  entries=[];blobs={};rawmap={}
  for suite in PLAN['order']:
   cr=BASE[len('candidate/'):]+f'/raw/{suite}/run.json';rr=BASE[len('candidate/'):]+f'/{PLAN["suites"][suite]["resultName"]}'
   cb=b'capture-unit';rb=b'result-unit';command=['/usr/bin/python3','unit-only']
   entries.append({'suite':suite,'command':command,'captureFile':cr,'captureSha256':sha256(cb).hexdigest(),'resultFile':rr,'resultSha256':sha256(rb).hexdigest()})
   blobs['candidate/'+cr]=cb;blobs['candidate/'+rr]=rb;rawmap[suite]={'command':command}
   for side in ('stdout.bin','stderr.bin','returncode.txt'):blobs[BASE+f'/raw/{suite}/'+side]=b'0\n' if side=='returncode.txt' else b''
  doc={'kind':g.INDEX_KIND,'version':1,'state':'completed','entries':entries,'sourceManifest':{'sha256':SOURCE,'entries':self.source['actual'],'fileCount':92}}
  blobs['candidate/checks-evidence-index.json']=json.dumps(doc).encode();m._f20_index(blobs,PLAN['order'],PLAN['suites'],BASE,rawmap)
 def test_actual_publication_nested_fields(self):
  publication={'index':{'ok':True,'sha256':'a'*64,'entries':20},'proof':{'ok':True,'sha256':'b'*64},'gate':{'state':'pending-independent-review','archiveCalls':0,'closureManifest':{'ok':True,'sha256':'c'*64}},'operatorArchivePending':True}
  m._f20_publication({'publication':publication},'a'*64,'b'*64,'c'*64,self.expected,self.source,PLAN['order'])
 def test_native_baseline_raw_null_count_metadata(self):
  suite='baseline-verify';directory=BASE+'/raw/'+suite;result={'fileCount':87,'recomputed':87,'mismatched':[],'manifestSha256':g._BASELINE_MANIFEST_SHA256};rb=json.dumps(result).encode();command=['/usr/bin/python3','-I','-B','unit-only']
  snap=cap.source_closure(R/'candidate');doc={'suite':suite,'command':command,'returncode':0,'sourceClosureOk':True,'sourceUnchanged':True,'sourceManifestBefore':snap,'sourceManifestAfter':snap,'resultFile':self.root+'/'+BASE+'/'+PLAN['suites'][suite]['resultName'],'resultSha256':sha256(rb).hexdigest(),'resultPassed':None,'resultTotal':None,'stdoutFile':'stdout.bin','stdoutSha256':sha256(b'').hexdigest(),'stdoutBytes':0,'stderrFile':'stderr.bin','stderrSha256':sha256(b'').hexdigest(),'stderrBytes':0}
  blobs={directory+'/run.json':json.dumps(doc).encode(),directory+'/stdout.bin':b'',directory+'/stderr.bin':b'',directory+'/returncode.txt':b'0\n',BASE+'/'+PLAN['suites'][suite]['resultName']:rb}
  m._f20_raw(blobs,suite,PLAN['suites'][suite]['resultName'],command,self.source,self.expected,g,R,BASE)
class RecordedProducerArchive(unittest.TestCase):
 def setUp(self):
  old=R.parent/'harness-linux-consumer-capacity-20261123/evidence'
  self.raw=(old/'VM-original-evidence.zip').read_bytes();self.delivery=json.loads((old/'VM-delivery.json').read_bytes());self.expected=json.loads((old/'payload-manifest.json').read_bytes())
 def test_real_prior_zip_encoding_is_accepted_by_archive_layer(self):
  with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
   names,blobs=m._f20_validate_archive(z,self.delivery,self.expected,self.delivery['members'],m._f20_frozen(self.expected))
  self.assertEqual(len(names),len(blobs));self.assertGreater(len(names),20)
 def test_legacy_consumer_gate_still_recomputes_real_prior_archive(self):
  result=m.verify_bundle(self.delivery,self.raw,self.expected);self.assertTrue(result['allPassed']);self.assertEqual(result['cases'],12)
if __name__=='__main__':unittest.main(verbosity=2)
