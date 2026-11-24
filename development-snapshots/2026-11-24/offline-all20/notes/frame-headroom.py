from pathlib import Path
from hashlib import sha256
import importlib.util,io,json
R=Path(__file__).resolve().parents[1]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('headroom_fixture',R/'checks/full20_archive_fixture.py');t=load('headroom_transfer',R/'operator/transfer.py');blobs,expected,final=f.make();d,raw=f.pack(blobs,expected,final);d['archiveBytesPayload']=raw;out=io.BytesIO();t.emit_frame(d,out);wire=out.getvalue();n=int.from_bytes(wire[len(t.MAGIC):len(t.MAGIC)+8],'big')
report={'unitOnly':True,'fabricatedFull20Evidence':True,'actualVMResult':False,'headerBytes':n,'capBytes':t.MAX_HEADER,'headroomBytes':t.MAX_HEADER-n,'archiveBytes':len(raw),'frozenSourceManifestSha256':expected['sourceManifestSha256'],'payloadSha256':sha256((R/'payload.json').read_bytes()).hexdigest(),'emitterSha256':sha256((R/'operator/transfer.py').read_bytes()).hexdigest(),'scope':'Measured this exact fabricated contract only; real metadata can differ and over-cap still fails closed.'};assert n<t.MAX_HEADER;(R/'evidence/frame-headroom.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
