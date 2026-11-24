"""Reuse the already-used 48/53 cases only as development regression."""
from pathlib import Path
from hashlib import sha256
import base64, csv, datetime, gzip, importlib.util, json, re, tarfile
w = Path(__file__).resolve().parent
repo = w.parents[1]/'exports/deepseek-harness-vm'
cases = json.loads((repo/'docs/security-workspace/ordinary-calibration-cases.json').read_text())['cases']
commit = 'f1291485808b66e20ddb6b01b10dc71b3df8c8ba'
prefix = 'BenchmarkPython-'+commit+'/'
with tarfile.open(w.parent/'harness-r3-owasp-20261103/upstream.tar.gz','r:gz') as archive:
    labels = archive.extractfile(prefix+'expectedresults-0.1.csv').read()
    for name,category,positive,cwe in csv.reader(labels.decode().splitlines()[1:]):
        if cwe!='94': continue
        assert re.fullmatch(r'BenchmarkTest[0-9]{5}',name) and positive in ['true','false']
        member = archive.getmember(prefix+'testcode/'+name+'.py')
        assert member.isfile() and member.size<=65536
        source = archive.extractfile(member).read().decode()
        cases.append({'id':name,'file':name+'.py','source':source})
assert len(cases)==101 and len({c['file'] for c in cases})==101
raw = (json.dumps(cases,ensure_ascii=False,indent=2)+'\n').encode()
(w/'regression-cases.json').write_bytes(raw)
freeze = {'createdAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'datasetSha256':sha256(raw).hexdigest(), 'alreadyUsedDevelopmentCases':101,
          'independentQualificationCases':0,
          'rules':{p:sha256((w/(p+'.candidate.json')).read_bytes()).hexdigest()
                   for p in ['arity17','combined20']}}
(w/'regression-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
spec = importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.validate()
native = (w.parent/'harness-ordinary-calibration-20261103/native-rules.py').read_text()
for phase in ['arity17','combined20']:
    payload = {'phase':phase,'cases':cases,'datasetSha256':freeze['datasetSha256'],
               'candidateRules':(w/(phase+'.candidate.json')).read_text(),
               'outputPolicy':(repo/'work/harness-purge-improved/package/scripts/security-output.sh').read_text()}
    source = 'PAYLOAD='+repr(base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode())+'\n'
    source += 'import datetime\nstartedAt=datetime.datetime.now(datetime.timezone.utc).isoformat()\n'
    source += native.replace('print(json.dumps(result))',"result['startedAt']=startedAt\nresult['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()\nprint(json.dumps(result))")
    result = json.loads(m.ssh('python3 -B -',input=source,timeout=110,phase='native-check').stdout)
    assert result['rulesSha256']==freeze['rules'][phase]
    (w/(phase+'-regression.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'phase':phase,'cases':101,'findings':len(result['native']['result']['results']),
                      'errors':len(result['native']['result']['errors'])}),flush=True)
