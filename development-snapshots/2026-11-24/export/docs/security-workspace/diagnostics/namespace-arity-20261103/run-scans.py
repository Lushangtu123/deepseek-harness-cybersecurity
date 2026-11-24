from pathlib import Path
from hashlib import sha256
import base64, datetime, gzip, importlib.util, json, sys
w = Path(__file__).resolve().parent
repo = w.parents[1] / 'exports/deepseek-harness-vm'
intent = json.loads((w/'intent.json').read_text())
raw = (w/'cases.json').read_bytes()
assert sha256(raw).hexdigest() == intent['datasetSha256']
assert sha256((repo/'work/harness-purge-improved/security-rules.json').read_bytes()).hexdigest() == intent['baselineSha256']
assert sha256((repo/'docs/security-workspace/ordinary-rules-combined.candidate.json').read_bytes()).hexdigest() == intent['combined19Sha256']
spec = importlib.util.spec_from_file_location('m',Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.validate()
native = (w.parent/'harness-ordinary-calibration-20261103/native-rules.py').read_text()
for phase in sys.argv[1:]:
    paths = {'baseline':repo/'work/harness-purge-improved/security-rules.json',
             'combined19':repo/'docs/security-workspace/ordinary-rules-combined.candidate.json',
             'arity17':w/'arity17.candidate.json','combined20':w/'combined20.candidate.json'}
    rules = paths[phase].read_text()
    payload = {'phase':phase,'candidateRules':rules,
               'outputPolicy':(repo/'work/harness-purge-improved/package/scripts/security-output.sh').read_text(),
               'cases':json.loads(raw),'datasetSha256':intent['datasetSha256']}
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()
    source = 'PAYLOAD='+repr(encoded)+'\nimport datetime\nstartedAt=datetime.datetime.now(datetime.timezone.utc).isoformat()\n'
    source += native.replace('print(json.dumps(result))',"result['startedAt']=startedAt\nresult['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()\nprint(json.dumps(result))")
    response = m.ssh('python3 -B -',input=source,timeout=110,phase='native-check')
    result = json.loads(response.stdout)
    assert result['rulesSha256'] == sha256(rules.encode()).hexdigest()
    (w/(phase+'-scan.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'phase':phase,'exitCode':result['scannerExitCode'],
                      'hits':len(result['native']['result']['results']),
                      'errors':len(result['native']['result']['errors'])}),flush=True)
