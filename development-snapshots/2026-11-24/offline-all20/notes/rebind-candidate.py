"""Metadata-only refresh; runtime source edits are from fixed DeepSeek packets."""
from pathlib import Path
from hashlib import sha256
import base64,json,types
R=Path(__file__).resolve().parents[1]
def h(raw):return sha256(raw).hexdigest()
def put(p,obj):p.write_text(json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
manifest=R/'candidate/protocol-manifest.json';m=json.loads(manifest.read_bytes())
old=m['files'];assert len(old)==92
m['files']={rel:h((R/'candidate'/rel).read_bytes()) for rel in old};m['totalBytes']=sum((R/'candidate'/rel).stat().st_size for rel in old)
m['note']=str(m.get('note',''))+'; 2026-11-24 all20 owned-fixture-link lifecycle; tools and baseline bytes unchanged.'
put(manifest,m);source=h(manifest.read_bytes())
p=R/'operator/suite-plan.json';plan=json.loads(p.read_bytes());plan['sourceManifestSha256']=source;put(p,plan)
s=json.loads((R/'START.json').read_bytes());protocol=json.loads((R/'PROTOCOL.json').read_bytes());s.update(date='2026-11-24',kind='fixture-return-full20-acceptance',baseline='work/harness-full20-integrated-20261123',guestRoot=protocol['guestRoot'],candidateManifestSha256=source,scope='All20 owned test-fixture link closure and file/dangling fail-closed scan; tools/baseline byte-original.');put(R/'START.json',s)
payload=json.loads((R/'payload.json').read_bytes());payload.update(guestRoot=protocol['guestRoot'],sourceManifestSha256=source)
for rel in payload['files']:
 raw=(R/rel).read_bytes();payload['files'][rel]={'bytes':base64.b64encode(raw).decode(),'sha256':h(raw)}
put(R/'payload.json',payload)
expected={k:payload[k] for k in ['caseIds','full20','guestRoot','sourceManifestSha256']};expected['files']={rel:{'sha256':row['sha256'],'bytes':len(base64.b64decode(row['bytes']))} for rel,row in payload['files'].items()};expected['payloadSha256']=h((R/'payload.json').read_bytes());put(R/'evidence/payload-manifest.json',expected)
required={**m['files'],'protocol-manifest.json':source};put(R/'evidence/closure-source-policy.json',{'kind':'predeclared-independent-actual-archive-source-coverage','requiredSourceFiles':required,'requiredCount':93,'mandatoryOther':['REPORT.md','phase-result.json','checks-evidence-index.json','proof.json'],'artifactCount':100,'enforceExactDeclaredKeySet':True,'missingExtraOrMismatch':'blocked','residualValidatorGapNotFixed':True})
assert all(h((R/'candidate'/rel).read_bytes())==v for rel,v in m['files'].items())
base=json.loads((R/'BASELINE-FREEZE.json').read_bytes())
protected={p:v for p,v in base['files'].items() if p.startswith('candidate/tools/') or p.startswith('candidate/baseline/')}
assert all(h((R/p).read_bytes())==v for p,v in protected.items())
put(R/'evidence/rebinding.json',{'sourceManifestSha256':source,'payloadSha256':expected['payloadSha256'],'files':len(expected['files']),'candidateFiles':len(m['files']),'protectedFilesUnchanged':len(protected),'guestRoot':protocol['guestRoot'],'formalTargets':'0/16','r3':'blocked'})
print(json.dumps({'source':source,'payloadFiles':len(payload['files']),'protectedUnchanged':len(protected)}))
