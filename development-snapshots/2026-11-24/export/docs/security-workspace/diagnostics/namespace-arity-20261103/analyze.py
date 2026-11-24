"""Verify receipts and report diagnostic tradeoffs without qualifying R3."""
from pathlib import Path
from hashlib import sha256
from collections import defaultdict
import ast, datetime, json
w = Path(__file__).resolve().parent
cases = json.loads((w/'cases.json').read_text())
intent = json.loads((w/'intent.json').read_text())
freeze = json.loads((w/'candidate-freeze.json').read_text())
regression = json.loads((w/'regression-freeze.json').read_text())
assert sha256((w/'cases.json').read_bytes()).hexdigest() == intent['datasetSha256'] == freeze['datasetSha256']
assert sha256((w/'intent.json').read_bytes()).hexdigest() == freeze['intentSha256']
assert sha256((w/'regression-cases.json').read_bytes()).hexdigest() == regression['datasetSha256']
assert len(cases)==26 and len({r['id'] for r in cases})==26
for row in cases:
    assert sha256(row['source'].encode()).hexdigest()==row['sha256']==intent['cases'][row['file']]
    assert row['qualifiesForR3'] is False

def sites(receipt):
    return {(r['check_id'],Path(r['path']).name,r['start']['line'],r['start']['col'],
             r['end']['line'],r['end']['col']) for r in receipt['native']['result']['results']}
def validate(receipt,sha,dataset):
    assert receipt['scannerExitCode']==0 and not receipt['native']['result']['errors']
    assert receipt['rulesSha256']==sha and receipt['datasetSha256']==dataset
    assert all(receipt[k] for k in ['temporaryRemoved','containerAbsent','runtimeRulesUnchanged','scannerManifestUnchanged'])
    assert receipt['imageId']=='sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7'
    assert receipt['native']['result']['version']=='1.182.1'

reports = {}
raw = {}
for phase in ['baseline','combined19','arity17','combined20']:
    result = json.loads((w/(phase+'-scan.json')).read_text())
    digest = {'baseline':intent['baselineSha256'], 'combined19':intent['combined19Sha256']}.get(phase)
    if digest is None:
        digest = freeze['packs'][phase]['sha256']
        assert sha256((w/(phase+'.candidate.json')).read_bytes()).hexdigest()==digest
        assert freeze['createdAt'] < result['startedAt']
    validate(result,digest,intent['datasetSha256'])
    scanned = {Path(p).name for p in result['native']['result']['paths']['scanned']}
    assert scanned == {r['file'] for r in cases}
    raw[phase] = result
    hits = sites(result)
    hit_files = {s[1] for s in hits}
    role_counts = defaultdict(lambda:{'sourceCases':0,'casesWithWarnings':0})
    for row in cases:
        role_counts[row['role']]['sourceCases']+=1
        role_counts[row['role']]['casesWithWarnings']+=row['file'] in hit_files
    missing = [r['id'] for r in cases if r['requiredArityCoverage'] and r['file'] not in hit_files]
    reports[phase] = {'sourceCases':len(cases),'scannedCases':len(scanned),
                      'rawRuleHits':len(result['native']['result']['results']), 'alertSites':len({s[1:] for s in hits}),
                      'requiredArityCases':6,'coveredRequiredArityCases':6-len(missing),
                      'missingRequiredArityCases':missing,'roleCounts':dict(role_counts),
                      'importResolutionControlsWithNoWarning':[r['id'] for r in cases
                            if r['role']=='authored-import-resolution-observation' and r['file'] not in hit_files]}
assert reports['baseline']['coveredRequiredArityCases']==2
assert reports['combined19']['coveredRequiredArityCases']==2
assert reports['arity17']['coveredRequiredArityCases']==6
assert reports['combined20']['coveredRequiredArityCases']==6
assert sites(raw['baseline']) <= sites(raw['arity17'])
assert sites(raw['combined19']) <= sites(raw['combined20'])
expected_additions = set()
for row in cases:
    for call in ast.walk(ast.parse(row['source'])):
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id in ['eval','exec'] and len(call.args) in [2,3]:
            expected_additions.add(('policy.harness.python.dynamic-code-namespace',row['file'],
                                    call.lineno,call.col_offset+1,call.end_lineno,call.end_col_offset+1))
assert len(expected_additions)==19
assert sites(raw['arity17'])-sites(raw['baseline']) == expected_additions
assert sites(raw['combined20'])-sites(raw['combined19']) == expected_additions
for phase in ['arity17','combined20']:
    # These warnings are a measured cost, not failed tests to tune away.
    assert reports[phase]['rawRuleHits']==21
    assert reports[phase]['roleCounts']['authored-shadowed-non-builtin']['casesWithWarnings']==2
    assert reports[phase]['roleCounts']['authored-complete-constraint']['casesWithWarnings']==2
    assert len(reports[phase]['importResolutionControlsWithNoWarning'])==4
    assert any(s[1:3]==('stdlib_collections.py',441) for s in sites(raw[phase]))

preserved = {}
repo = w.parents[1]/'exports/deepseek-harness-vm'
synthetic_raw = (repo/'docs/security-workspace/ordinary-calibration-cases.json').read_bytes()
regression_cases = json.loads((w/'regression-cases.json').read_text())
original_synthetic = json.loads(synthetic_raw)['cases']
assert regression_cases[:48] == original_synthetic
old_index = json.loads((w.parent/'harness-r3-combined-20261103/owasp-index.json').read_text())
assert {r['id']:sha256(r['source'].encode()).hexdigest() for r in regression_cases[48:]} == {r['id']:r['sha256'] for r in old_index['cases']}
for phase,oldphase in [('arity17','baseline'),('combined20','combined')]:
    result = json.loads((w/(phase+'-regression.json')).read_text())
    validate(result,freeze['packs'][phase]['sha256'],regression['datasetSha256'])
    assert regression['createdAt'] < result['startedAt']
    old = set()
    for dataset in ['synthetic','owasp']:
        receipt = json.loads((w.parent/'harness-r3-combined-20261103'/(dataset+'-'+oldphase+'.json')).read_text())
        expected_dataset = sha256(synthetic_raw).hexdigest() if dataset=='synthetic' else sha256((w.parent/'harness-r3-combined-20261103/owasp-index.json').read_bytes()).hexdigest()
        expected_rules = intent['baselineSha256'] if oldphase=='baseline' else intent['combined19Sha256']
        validate(receipt,expected_rules,expected_dataset)
        old |= sites(receipt)
    new = sites(result)
    assert len(new)==len(result['native']['result']['results'])
    assert old == new, (old-new,new-old)
    scanned = {Path(p).name for p in result['native']['result']['paths']['scanned']}
    expected = {r['file'] for r in json.loads((w/'regression-cases.json').read_text())
                if phase=='combined20' or not r['file'].endswith('.php')}
    assert scanned==expected
    preserved[phase]={'oldRuleHitsPreserved':len(old),'currentRawRuleHits':len(result['native']['result']['results']),
                      'sourceCases':101,'actuallyScanned':len(scanned),
                      'notScannedPhpCases':101-len(scanned),'newHoldout':False}

runtime = json.loads((w/'native-oracle.json').read_text())
protocol = json.loads((w/'protocol.json').read_text())
assert runtime['imageId']==protocol['imageId']==raw['baseline']['imageId']
assert runtime['result']['python']=='3.12.15'
final_state = json.loads((w/'final-state.json').read_text())
assert final_state['ok'] and final_state['rulesSha256']==intent['baselineSha256']
assert final_state['runtimeRules']==16 and final_state['programFilesMatchedToRepoSource']==165
assert final_state['researchCandidatesInstalled'] is False
provenance = json.loads((w/'protocol-provenance.json').read_text())
for key,name in [('protocolSha256','protocol.json'),('probeSha256','probe.py'),('intentSha256','intent.json'),('candidateFreezeSha256','candidate-freeze.json')]:
    assert provenance[key]==sha256((w/name).read_bytes()).hexdigest()
assert protocol['sources']=={r['file']:r['sha256'] for r in cases if r['role']!='reused-upstream-normal-source'}
assert runtime['ok'] and runtime['result']['ok'] and len(runtime['result']['observations'])==34
assert runtime['result']['protocolSha256']==sha256((w/'protocol.json').read_bytes()).hexdigest()
assert runtime['result']['probeSha256']==sha256((w/'probe.py').read_bytes()).hexdigest()==protocol['probeSha256']
observed = runtime['result']['observations']
assert {r['id'] for r in observed} == {r['id'] for r in protocol['vectors']}
vectors = {r['id']:r for r in protocol['vectors']}
rejected = bypassed = 0
for row in observed:
    vector = vectors[row['id']]
    assert row['caseId']==vector['caseId'] and row['arguments']==vector['args']
    assert row['error']==vector.get('error') and len(row['dynamicFrames'])==vector['dynamicFrames']
    if 'expected' in vector:
        assert type(row['result']) is type(vector['expected']) and row['result']==vector['expected']
    else:
        assert row['result'] is None
    assert row['sourceSha256']==protocol['sources'][row['caseId']+'.py']
    assert row['qualifiesForR3'] is False
    case = next(c for c in cases if c['id']==row['caseId'])
    assert all(f['line'] in {s['line'] for s in case['sites']} for f in row['dynamicFrames'])
    rejected += case['role']=='authored-complete-constraint' and row['error']=='ValueError' and not row['dynamicFrames']
    bypassed += case['role'] in ['authored-conditional-bypass','authored-after-check-overwrite','authored-after-check-mutation'] and row['result']==17389*7919 and bool(row['dynamicFrames'])

normal_roles = {'authored-complete-constraint','authored-fixed-selection',
                'authored-fixed-literal','authored-shadowed-non-builtin','reused-upstream-normal-source'}
summary = {'version':1,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'scope':'offline research candidate; no runtime installation or finding-state change',
           'comparisons':reports, 'regression':preserved,
           'newRuleEvidence':{'authoredMatchedSites':sum(s[1] not in ['stdlib_ast.py','stdlib_collections.py'] for s in expected_additions),
                              'reusedUpstreamMatchedSites':sum(s[1] in ['stdlib_ast.py','stdlib_collections.py'] for s in expected_additions),
                              'exactNewHitIdentityChecked':True,'normalControlsDesignedToMatchSyntax':True},
           'runtime':{'authoredSourceCases':len(protocol['sources']),'observations':len(observed),'independentCases':0,
                      'completeConstraintRejectedMarker':rejected,'conditionalOrPostCheckBypassWitnesses':bypassed,
                      'programFilesMatchedDuringProbe':runtime['programFilesMatched'],
                      'databaseLogicalDigestsMatchedDuringProbe':runtime['databaseLogicalDigestsMatched']},
           'normalControlWarningObservations':{'cases':sum(r['role'] in normal_roles for r in cases),
                  'arity17CasesWithWarnings':sum(r['role'] in normal_roles and any(s[1]==r['file'] for s in sites(raw['arity17'])) for r in cases),
                  'meaning':'Selected syntactic controls designed to match; not a cost estimate, population false-positive rate or R3 metric'},
           'limitations':['sink-only; no source/callee/guard proof',
                          '4 explicit builtins/import-alias controls still missed',
                          'keywords, star-arguments, dynamic binding, object semantics not covered',
                          'exec closure keyword, Python3.13 keyword namespaces, getattr and __builtins__ forms not evaluated',
                          'combined dataflow/sink duplicates and metadata consumers not evaluated; no-automatic-suppression is descriptive metadata only',
                          'host/VM timestamps are execution logs, not trusted preregistration',
                          'exec one-argument locals observation is pinned to Python3.12 behavior',
                          'all new controls authored; upstream normal files and 101 regression cases reused',
                          'bounded arithmetic witness is not an HTTP or impact demonstration'],
           'rulesDeployed':False,'ordinaryModeReleased':False,'r3Qualified':False,
           'independentQualificationCasesAdded':0}
assert summary['normalControlWarningObservations']['cases']==10 and summary['normalControlWarningObservations']['arity17CasesWithWarnings']==9
assert rejected==2 and bypassed==6
(w/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'ok':True,'coveredRequiredArityCases':6,'normalControlWarnings':9,'selectedNormalControls':10,
                  'regression':preserved,'runtimeObservations':34,'r3Qualified':False}))
