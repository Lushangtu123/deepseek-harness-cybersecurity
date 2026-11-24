from pathlib import Path
from hashlib import sha256
import ast,difflib,json,sys
R=Path(__file__).resolve().parents[1];d=R/sys.argv[1];prep=json.loads((d/'prepared.json').read_bytes());status=json.loads((d/'deepseek-status.json').read_bytes());assert status['state']=='completed'
receipt=json.loads((d/'deepseek.receipt.json').read_bytes());assert receipt['model'].startswith('deepseek-flash');assert receipt['choices'][0]['finish_reason']=='stop'
for rel,h in prep['sources'].items():assert sha256((R/rel).read_bytes()).hexdigest()==h,rel
s=(d/'deepseek.review.md').read_text().strip()
if s.startswith('```'):s=s.split('\n',1)[1].rsplit('```',1)[0]
patch=json.loads(s);assert isinstance(patch.get('edits'),list)
before={};after={}
for e in patch['edits']:
 rel=e['path'];assert rel in prep['allowed'],rel
 if rel not in before:before[rel]=(R/rel).read_text();after[rel]=before[rel]
 assert e['old'] and after[rel].count(e['old'])==1,(rel,'anchor-count')
 after[rel]=after[rel].replace(e['old'],e['new'],1)
for rel,new in after.items():ast.parse(new,filename=rel)
for rel,new in after.items():(R/rel).write_text(new)
(d/'applied.diff').write_text(''.join(''.join(difflib.unified_diff(before[n].splitlines(True),after[n].splitlines(True),fromfile='before/'+n,tofile='after/'+n)) for n in after))
(d/'applied.json').write_text(json.dumps({'model':receipt['model'],'responseId':receipt['id'],'files':{n:{'before':sha256(before[n].encode()).hexdigest(),'after':sha256(after[n].encode()).hexdigest()} for n in after},'allowedOnly':True,'anchorsUnique':True,'syntaxParsed':True},indent=2)+'\n')
print(json.dumps({'applied':list(after),'edits':len(patch['edits'])}))
