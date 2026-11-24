from pathlib import Path
from hashlib import sha256
from collections import Counter
import importlib.util,json,re
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm';v=w.parent/'harness-namespace-review-v3-20261103';prior=w.parent/'harness-namespace-arity-20261103'
plan=json.loads((v/'protocol.json').read_text());native=json.loads((v/'native-oracle.json').read_text());result=native['result']
assert native['ok'] and result['ok'] and native['imageId']==plan['imageId'] and result['python']=='3.12.15'
assert result['protocolSha256']==sha256((v/'protocol.json').read_bytes()).hexdigest() and result['probeSha256']==sha256((v/'probe.py').read_bytes()).hexdigest()==plan['probeSha256']
for name,digest in plan['reviewFiles'].items():assert sha256((v/'review'/name).read_bytes()).hexdigest()==digest
for name,digest in plan['sources'].items():assert sha256((v/'src'/name).read_bytes()).hexdigest()==digest
for name in ['python_namespace_review.py','python_namespace_review.test.py']:
 assert (repo/'scripts'/name).read_bytes()==(v/'review/scripts'/name).read_bytes()
assert len(plan['sources'])==29 and native['programFilesMatched']==165 and native['databaseLogicalDigestsMatched']==40
assert all(native[k] for k in ['manifestAndRulesMatched','containerRemoved','temporaryRemoved','volumeSetUnchanged'])
assert re.search(r'Ran 23 tests\b',result['unitTestOutput']) and result['unitTestExitCode']==0
state=json.loads((w/'final-state.json').read_text());baseline=json.loads((prior/'intent.json').read_text())
assert state['ok'] and state['programFilesMatched']==165 and state['runtimeRules']==16 and not state['namespaceReviewerDeployed']
assert state['rulesSha256']==baseline['baselineSha256']
program=repo/'work/harness-purge-improved/package'
assert json.loads((w/'program-source.json').read_text())=={str(p.relative_to(program)):sha256(p.read_bytes()).hexdigest() for p in program.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
reports=result['reports'];assert reports['arity17']==reports['combined20']
for phase in ['arity17','combined20','anchors']:
 origin=(prior/(phase+'-scan.json')) if phase!='anchors' else w/'anchor-scan.json'
 receipt=json.loads(origin.read_text());assert sha256(origin.read_bytes()).hexdigest()==plan['scans'][phase]['originalReceiptSha256']
 assert receipt['imageId']==plan['imageId'] and receipt['scannerExitCode']==0 and not receipt['native']['result']['errors'] and receipt['native']['result']['version']=='1.182.1'
 assert all(receipt[k] for k in ['runtimeRulesUnchanged','scannerManifestUnchanged','temporaryRemoved','containerAbsent'])
 raw=(v/'review'/(phase+'-scan.json')).read_bytes();assert sha256(raw).hexdigest()==plan['scans'][phase]['rawResultSha256']
 scan=json.loads(raw);assert scan==receipt['native']['result']
 expected={(h['path'].removeprefix('/src/'),h['check_id'],h['start']['line'],h['start']['col'],h['end']['line'],h['end']['col'],h['start']['offset'],h['end']['offset']) for h in scan['results'] if h['check_id']=='policy.harness.python.dynamic-code-namespace'}
 report=reports[phase];assert report['version']==2 and report['state']=='completed' and not report['unmatchedAnchors'] and not report['changesFindingDisposition'] and not report['r3Qualified']
 actual={(r['file'],r['rule'],r['anchor']['line'],r['anchor']['col'],r['anchor']['endLine'],r['anchor']['endCol'],r['anchor']['offset'],r['anchor']['endOffset']) for r in report['observations']}
 assert actual==expected and len(actual)==plan['expectedObservationsByPhase'][phase]
 assert report['ignoredHits']=={'different-rule':2 if phase!='anchors' else 0,'unsupported-rule-prefix':0,'unpinned-path':0}
 for row in report['observations']:
  assert row['sourceSha256']==plan['sources'][row['file']] and row['disposition']=='unverified'
  assert row['callee']['builtinIdentity']=='unverified' and row['source']['externalControl']=='unverified'
 constraints={r['file'] for r in report['observations'] if r['constraint']['state']=='fixed-set-guard-observed'}
 assert constraints==(set(plan['expectedConditionalGuardFiles']) if phase!='anchors' else set())

# Replay the exact immutable bytes on this host; no source module is executed.
spec=importlib.util.spec_from_file_location('offline_review',repo/'scripts/python_namespace_review.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for phase in reports:
 manifest=json.loads((v/'review'/(phase+'-manifest.json')).read_text());scan=json.loads((v/'review'/(phase+'-scan.json')).read_text())
 assert m.review_namespace_batch((v/'src').resolve(),manifest,scan)==reports[phase]
summary={'version':1,'scope':'offline structural evidence final correction (run v3, output schema v2); not deployed',
         'reusedSourceCases':26,'newAuthoredBytePositionCases':3,'sourceCases':29,
         'oldUniqueNamespaceObservations':19,'duplicatePackResultsCountedOnce':True,
         'conditionalGuardObservations':2,'oldConstraintsUnresolved':17,
         'newBytePositionObservations':6,'newBytePositionConstraintsUnresolved':6,
         'rawWarningsPerOldScan':21,'warningsSuppressed':0,'findingDispositionsChanged':0,
         'hostGuestReportsEqual':True,'unitTestsMac':23,'unitTestsVM':23,'guestPython':'3.12.15','scannerVersion':'1.182.1',
         'sourceKinds':dict(Counter(r['source']['kind'] for r in reports['combined20']['observations'])),
         'programFilesMatched':165,'databaseLogicalDigestsMatched':40,'runtimeRulesUnchanged':True,
         'temporaryAndContainersRemoved':True,'rulesDeployed':False,'reviewerDeployed':False,
         'independentQualificationCasesAdded':0,'r3Qualified':False,
         'limitations':['unsigned evidence is consistency-bound, not cryptographic origin attestation',
                        'parameter names do not establish external control; builtin identity and string semantics remain unverified',
                        'fixed-membership values may themselves execute code',
                        'whole-file namespace conservatism can leave unrelated cases unresolved',
                        'UTF8-cookie-clean source only; nonUTF8 declarations, BOM and lone CR unmatched',
                        'no-direct-conflict-observed is lexical only; indirect builtin mutation/import side effects remain possible',
                        'no new independent holdout or population false-positive-rate claim',
                        'production file:line pipeline lacks required exact byte ranges',
                        'scanner alias/keyword/dynamic-call coverage remains open']}
(w/'results.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
