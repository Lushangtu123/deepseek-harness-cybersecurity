from hashlib import sha256
from pathlib import Path
import ast
import base64
import importlib.util
import json
import re
import sys
import uuid

root = Path(__file__).resolve().parent
work = root.parents[1]
repo = work.parent/'exports/deepseek-harness-vm'

def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def load(path):
    return json.loads(path.read_bytes())


def digest(raw):
    return sha256(raw).hexdigest()


def prepare():
    data,sources,sites=module(work/'harness-r3-independent-acceptance-20261111/preflight-r2/inputs.py').build()
    source='from flask import request\nimport builtins\ndef route():\n\tlabel="中文😀"\n\tvalue=request.args.get("value")\n\tif value in ("foo", "bar"):\n\t\teval(value)\n\texec(value); eval(value)\n\treturn (\n\t eval(\n\t  value\n\t )\n\t)\ndef nested(value):\n\treturn eval(eval(value))\ndef explicit(value):\n\treturn builtins.eval(value)\n'.replace('\n','\r\n')
    sources['boundary.py']=source.encode()
    files={'sources/'+n:raw for n,raw in sources.items()}
    files['historical-dataset.json']=json.dumps(data,indent=2).encode()
    names={'policy.json':'docs/security-workspace/review-quality-policy.candidate.json','ledger.json':'docs/security-workspace/review-sample-ledger.json','baseline-rules.json':'work/harness-purge-improved/security-rules.json','candidate-rules.json':'docs/security-workspace/ordinary-rules-combined.candidate.json','security-output.sh':'work/harness-purge-improved/package/scripts/security-output.sh'}
    for n in ['reviewer_snapshot.py','reviewer_storage.py','review_quality_gate.mjs','eval_locations.test.py']:names['scripts/'+n]='scripts/'+n
    for n in ['eval_evidence_batch.py','eval_guard_review.py','eval_import_review.py']:
        names['reviewer-modules/'+n]='work/harness-purge-improved/package/scripts/'+n
        names['work/harness-purge-improved/package/scripts/'+n]='work/harness-purge-improved/package/scripts/'+n
    for n in ['review-locations-v3.test.mjs','review-quality-gate.test.mjs']:names['work/harness-purge-improved/tests/'+n]='work/harness-purge-improved/tests/'+n
    names['work/harness-purge-improved/package/lib/redteam/personal-python-evidence.mjs']='work/harness-purge-improved/package/lib/redteam/personal-python-evidence.mjs'
    files.update({n:(repo/path).read_bytes() for n,path in names.items()})
    historical=load(repo/'docs/security-workspace/combined-rules-results.json')
    identity={key:historical[key] for key in ['imageId','scannerVersion','candidateRulesSha256']};identity['baselineRulesSha256']=historical['baseRulesSha256']
    identity['scannerArguments']=['--config','/policy/rules.json','--json','--output','/out/result.json','--metrics=off','--disable-version-check','--jobs','1','--timeout','5','--max-target-bytes','1000000','/src'];identity['scannerAdapterSha256']=digest(files['security-output.sh'])
    files['scanner-identity.json']=json.dumps(identity).encode()
    text=(work/'harness-workspace-bootstrap-20261110/stage-guest.py').read_text()
    functions=[ast.get_source_segment(text,n) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name in {'digest','identity'}];assert len(functions)==2
    files['identity-code.py']='\n\n'.join(functions).encode()
    for n in ['score.mjs','managed-live.mjs']:files[n]=(root/n).read_bytes()
    return {'checks':{n:digest(raw) for n,raw in files.items()},'files':{n:base64.b64encode(raw).decode() for n,raw in files.items()}}

def launch(bridge):
    intent = root/'vm-intent.json'
    if intent.exists():
        raise ValueError('Original request already exists. Query it before any retry.')
    payload = prepare()
    raw = json.dumps(payload)
    worker = (root/'worker.py').read_text()
    remote = '/home/purge/.cache/r3-independent-python-locations-'+uuid.uuid4().hex[:12]
    write(intent, {'remoteRoot':remote,'inputSha256':digest(raw.encode()),'workerSha256':digest(worker.encode()),'files':payload['checks']})
    (root/'vm-input.json').write_text(raw)
    script = f'REMOTE={remote!r}\nWORKER={worker!r}\nPAYLOAD={raw!r}\n'+'''
from pathlib import Path
import json,os,subprocess
os.umask(0o077)
root=Path(REMOTE);root.mkdir(mode=0o700)
assert root.resolve()==root and os.geteuid()==1000
(root/'worker.py').write_text(WORKER);(root/'input.json').write_text(PAYLOAD)
with (root/'worker.stdout').open('wb') as out,(root/'worker.stderr').open('wb') as err:
 p=subprocess.Popen(['/usr/bin/timeout','--signal=TERM','--kill-after=5','360','/usr/bin/python3','-I','-B',str(root/'worker.py')],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,close_fds=True)
print(json.dumps({'state':'submitted','pid':p.pid}))
'''
    answer = bridge.call(script, 20)
    write(root/'vm-submitted.json', answer)
    print(json.dumps(answer))


def poll(bridge):
    intent = load(root/'vm-intent.json')
    remote = intent['remoteRoot']
    assert re.fullmatch(r'/home/purge/\.cache/r3-independent-python-locations-[0-9a-f]{12}', remote)
    script = f'REMOTE={remote!r}\n'+'''
from pathlib import Path
from hashlib import sha256
import json
root=Path(REMOTE)
status=root/'status.json'
value=json.loads(status.read_bytes()) if status.exists() else {'state':'not-yet-observed'}
if value['state']=='completed':
 raw=(root/'result.json').read_bytes()
 assert sha256(raw).hexdigest()==value['resultSha256']
 value['result']=raw.decode()
print(json.dumps(value))
'''
    answer = bridge.call(script, 20)
    if answer['state'] == 'completed':
        raw = answer.pop('result').encode()
        assert digest(raw) == answer['resultSha256']
        result = json.loads(raw)
        assert result['inputSha256'] == intent['inputSha256'] and result['sourcesVerified'] == intent['files']
        (root/'vm-result.json').write_bytes(raw)
        for name,text in result['artifacts'].items():
            path = root/'guest-evidence'/name
            assert path.is_relative_to(root/'guest-evidence') and '..' not in Path(name).parts
            assert digest(text.encode()) == result['artifactSha256'][name]
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text)
    write(root/'vm-poll.json', answer)
    print(json.dumps(answer))


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        print(json.dumps(prepare()['checks'], indent=2))
    else:
        {'launch':launch, 'poll':poll}[sys.argv[1]](module(root.parent/'vm-bridge.py'))
