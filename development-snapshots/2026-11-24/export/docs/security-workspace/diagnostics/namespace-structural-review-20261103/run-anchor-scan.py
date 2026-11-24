from pathlib import Path
from hashlib import sha256
import base64,datetime,gzip,importlib.util,json
w=Path(__file__).resolve().parent;repo=w.parents[1]/'exports/deepseek-harness-vm'
if (w/'anchor-intent.json').exists():raise SystemExit('Anchor intent is frozen')
source='def run(value):\n    if value not in ("6*7",):\n        return "blocked"\n    scope = {}\n    "中文字🙂"; eval(value, scope); exec(value, scope)\n'
tabbed=source.replace('        ','\t\t').replace('    ','\t')
cases=[{'id':'unicode-lf','file':'unicode-lf.py','source':source},
       {'id':'unicode-crlf','file':'unicode-crlf.py','source':source.replace('\n','\r\n')},
       {'id':'unicode-tabs','file':'unicode-tabs.py','source':tabbed}]
raw=(json.dumps(cases,ensure_ascii=False,indent=2)+'\n').encode();(w/'anchor-cases.json').write_bytes(raw)
rules=(repo/'docs/security-workspace/namespace-arity17.candidate.json').read_bytes()
intent={'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'caseHashes':{r['file']:sha256(r['source'].encode()).hexdigest() for r in cases},'rulesSha256':sha256(rules).hexdigest(),'datasetSha256':sha256(raw).hexdigest(),'independentQualificationCases':0,'claim':'real scanner byte/column binding diagnostics only'}
(w/'anchor-intent.json').write_text(json.dumps(intent,indent=2)+'\n')
payload={'phase':'anchor','candidateRules':rules.decode(),'cases':cases,'datasetSha256':intent['datasetSha256'],'outputPolicy':(repo/'work/harness-purge-improved/package/scripts/security-output.sh').read_text()}
spec=importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.validate()
source='PAYLOAD='+repr(base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode())+'\n'+(w.parent/'harness-ordinary-calibration-20261103/native-rules.py').read_text()
result=json.loads(m.ssh('python3 -B -',input=source,timeout=110,phase='native-check').stdout)
assert result['rulesSha256']==intent['rulesSha256'] and result['scannerExitCode']==0 and not result['native']['result']['errors']
(w/'anchor-scan.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'scanned':len(result['native']['result']['paths']['scanned']),'findings':len(result['native']['result']['results']),'errors':len(result['native']['result']['errors'])}))
