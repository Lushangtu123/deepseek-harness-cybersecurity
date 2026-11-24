"""Verify receipts and report diagnostic tradeoffs without qualifying R3."""
from pathlib import Path
from hashlib import sha256
from collections import defaultdict
import datetime, json
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
                      'rawRuleHits':len(result['native']['result']['results']), 'alertSites':len(hits),
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
for phase in ['arity17','combined20']:
    # These warnings are a measured cost, not failed tests to tune away.
    assert reports[phase]['rawRuleHits']==21
    assert reports[phase]['roleCounts']['authored-shadowed-non-builtin']['casesWithWarnings']==2
    assert reports[phase]['roleCounts']['authored-complete-constraint']['casesWithWarnings']==2
    assert len(reports[phase]['importResolutionControlsWithNoWarning'])==4
    assert any(s[1:3]==('stdlib_collections.py',441) for s in sites(raw[phase]))

preserved = {}
for phase,oldphase in [('arity17','baseline'),('combined20','combined')]:
    result = json.loads((w/(phase+'-regression.json')).read_text())
    validate(result,freeze['packs'][phase]['sha256'],regression['datasetSha256'])
    assert regression['createdAt'] < result['startedAt']
    old = set()
    for dataset in ['synthetic','owasp']:
        receipt = json.loads((w.parent/'harness-r3-combined-20261103'/(dataset+'-'+oldphase+'.json')).read_text())
        old |= sites(receipt)
    new = sites(result)
    assert old <= new, old-new
    scanned = {Path(p).name for p in result['native']['result']['paths']['scanned']}
    expected = {r['file'] for r in json.loads((w/'regression-cases.json').read_text())
                if phase=='combined20' or not r['file'].endswith('.php')}
    assert scanned==expected
    preserved[phase]={'oldRuleHitsPreserved':len(old),'currentRawRuleHits':len(result['native']['result']['results']),
                      'sourceCases':101,'actuallyScanned':len(scanned),
                      'notScannedPhpCases':101-len(scanned),'newHoldout':False}

runtime = json.loads((w/'native-oracle.json').read_text())
protocol = json.loads((w/'protocol.json').read_text())
assert runtime['ok'] and runtime['result']['ok'] and len(runtime['result']['observations'])==34
assert runtime['result']['protocolSha256']==sha256((w/'protocol.json').read_bytes()).hexdigest()
assert runtime['result']['probeSha256']==sha256((w/'probe.py').read_bytes()).hexdigest()==protocol['probeSha256']
observed = runtime['result']['observations']
assert {r['id'] for r in observed} == {r['id'] for r in protocol['vectors']}
for row in observed:
    assert row['sourceSha256']==protocol['sources'][row['caseId']+'.py']
    assert row['qualifiesForR3'] is False
    case = next(c for c in cases if c['id']==row['caseId'])
    assert all(f['line'] in {s['line'] for s in case['sites']} for f in row['dynamicFrames'])

normal_roles = {'authored-complete-constraint','authored-fixed-selection',
                'authored-fixed-literal','authored-shadowed-non-builtin','reused-upstream-normal-source'}
summary = {'version':1,'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'scope':'offline research candidate; no runtime installation or finding-state change',
           'comparisons':reports, 'regression':preserved,
           'runtime':{'authoredSourceCases':24,'observations':34,'independentCases':0,
                      'completeConstraintRejectedMarker':2,'conditionalOrPostCheckBypassWitnesses':6,
                      'programFilesMatchedDuringProbe':runtime['programFilesMatched'],
                      'databaseLogicalDigestsMatchedDuringProbe':runtime['databaseLogicalDigestsMatched']},
           'normalPathWarningCost':{'cases':sum(r['role'] in normal_roles for r in cases),
                  'arity17CasesWithWarnings':sum(r['role'] in normal_roles and any(s[1]==r['file'] for s in sites(raw['arity17'])) for r in cases),
                  'meaning':'Selected diagnostic examples; not a population false-positive rate or R3 metric'},
           'limitations':['sink-only; no source/callee/guard proof',
                          '4 explicit builtins/import-alias controls still missed',
                          'keywords, star-arguments, dynamic binding, object semantics not covered',
                          'all new controls authored; upstream normal files and 101 regression cases reused',
                          'bounded arithmetic witness is not an HTTP or impact demonstration'],
           'rulesDeployed':False,'ordinaryModeReleased':False,'r3Qualified':False,
           'independentQualificationCasesAdded':0}
assert summary['normalPathWarningCost']['cases']==10 and summary['normalPathWarningCost']['arity17CasesWithWarnings']==9
(w/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'ok':True,'coveredRequiredArityCases':6,'normalPathWarnings':'9/10 diagnostic controls',
                  'regression':preserved,'runtimeObservations':34,'r3Qualified':False}))
