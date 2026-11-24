"""Independent read-only actual ZIP source-coverage compensation; never imports ZIP code."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import io,json,zipfile
R=Path(__file__).resolve().parents[1];E=R/'execution';P=json.loads((R/'evidence/closure-source-policy.json').read_bytes())
def valid(name):
 p=PurePosixPath(name);return not p.is_absolute() and '..' not in p.parts and str(p)==name

def check(z,closure):
 files=closure['files'];maps=closure['validatedArtifactMap'];required=P['requiredSourceFiles'];assert len(required)==93 and len(maps)==100
 allowed=set(required)|set(P['mandatoryOther'])|{row['archivePath'] for row in maps}
 assert type(files) is dict and set(files)==allowed,'closure-coverage-keyset'
 assert closure['fileCount']==len(files),'closure-file-count'
 for name,expected in required.items():
  assert valid(name),'unsafe-required-path'
  assert files.get(name)==expected,'closure-source-declaration:'+name
  assert sha256(z.read('candidate/'+name)).hexdigest()==expected,'actual-archive-source:'+name
 return {'sourceMembers':len(required),'closureMembers':len(files),'validatedArtifactCount':len(maps)}
raw=(E/'evidence/VM-original-evidence.zip').read_bytes();delivery=json.loads((E/'evidence/VM-delivery.json').read_bytes());accepted=json.loads((E/'evidence/VM-acceptance.json').read_bytes());assert accepted.get('allPassed') is True
assert sha256(raw).hexdigest()==delivery['archiveSha256']
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 body=z.read('candidate/closure-manifest.json');assert sha256(body).hexdigest()==delivery['result']['publication']['gate']['closureManifest']['sha256'];closure=json.loads(body);positive=check(z,closure)
 mutation=json.loads(body);mutation['files'].pop('tools/buffer_protocol.py');mutation['fileCount']=len(mutation['files'])
 try:check(z,mutation)
 except AssertionError as ex:negative=str(ex)
 else:raise AssertionError('missing-source-map-was-accepted')
report={'kind':'independent-actual-VM-archive-source-coverage','allPassed':True,'originalArchiveSha256':sha256(raw).hexdigest(),'sourceManifestSha256':P['requiredSourceFiles']['protocol-manifest.json'],'positive':positive,'copyOnlyNegativeReason':negative,'originalArchiveUnchanged':sha256((E/'evidence/VM-original-evidence.zip').read_bytes()).hexdigest()==sha256(raw).hexdigest(),'residualGenericValidatorNotClaimedFixed':True,'r3':'blocked','formalTargets':'0/16'}
(R/'evidence/actual-archive-source-coverage.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
