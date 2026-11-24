from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import base64
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import time
import traceback

root = Path(__file__).resolve().parent
home = Path('/home/purge')
daily = home / '.dsh-improved'
installed = home / 'tools/dsh-purge-personal-1.1.77-personal.1'
runtime = home / 'tools/harness-improved-runtime/node_modules'
workbench = home / 'tools/security-workbench'
node = str(home / '.local/node/bin/node')
python = ['/usr/bin/python3', '-I', '-B', '-S']
docker = ['/usr/bin/sudo', '-n', '/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', '--config', str(root/'docker-config')]


def write(name, value):
    path = root / name
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def load(name):
    return json.loads((root / name).read_bytes())


def run(argv, timeout=45, codes=(0,)):
    output = subprocess.run(argv, cwd=root, timeout=timeout, stdin=subprocess.DEVNULL, capture_output=True)
    if output.returncode not in codes:
        raise ValueError(f'Command {Path(argv[0]).name} failed ({output.returncode}): {output.stderr[-2000:].decode(errors="replace")}')
    return output


def scan(name, rules, identity):
    container = root.name + '-' + name
    args = [*docker, 'run', '--rm', '--pull', 'never', '--name', container, '--network', 'none', '--read-only',
            '--user', '1000:1000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '768m',
            '--memory-swap', '768m', '--cpus', '1', '--pids-limit', '64', '--log-driver', 'none',
            '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=134217728,mode=1777',
            '--tmpfs', '/out:rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=0700',
            '--env', 'HOME=/tmp', '--env', 'SEMGREP_SEND_METRICS=off',
            '--mount', f'type=bind,src={root / "sources"},dst=/src,readonly',
            '--mount', f'type=bind,src={root / rules},dst=/policy/rules.json,readonly',
            '--mount', f'type=bind,src={root / "security-output.sh"},dst=/policy-output.sh,readonly',
            '--entrypoint', '/bin/sh', identity['imageId'], '/policy-output.sh', '/out', '--deadline-seconds', '60',
            'semgrep', 'scan', *identity['scannerArguments']]
    write(name+'-command.json', args)
    try:
        output = run(args, timeout=75)
        (root / (name+'-stdout.json')).write_bytes(output.stdout)
        (root / (name+'-stderr.txt')).write_bytes(output.stderr)
    finally:
        if run([*docker, 'ps', '-aq', '--filter', f'name=^/{container}$'], 10).stdout.strip():
            raise ValueError('Diagnostic scanner container still present')
    raw = json.loads(output.stdout)['result']
    assert raw['version'] == identity['scannerVersion'] and raw['errors'] == []
    assert set(raw['paths']['scanned']) == {'/src/'+x.name for x in (root/'sources').iterdir()}
    write(name+'-scan.json', raw)


def main():
    assert os.geteuid()==1000 and root.resolve()==root
    payload=load('input.json')
    for name,encoded in payload['files'].items():
        path=root/name;assert path.is_relative_to(root) and '..' not in Path(name).parts
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);data=base64.b64decode(encoded,validate=True)
        assert sha256(data).hexdigest()==payload['checks'][name];path.write_bytes(data)
    (root/'docker-config').mkdir(mode=0o700)
    protected={};exec(compile((root/'identity-code.py').read_text(),'identity-code.py','exec'),globals(),protected)
    identify=protected['identity'];globals()['digest']=protected['digest'];before=identify()
    identity=load('scanner-identity.json')
    actual=next(t for t in json.loads((workbench/'images.json').read_bytes())['tools'] if t['tool']=='semgrep')
    assert actual['imageId']==identity['imageId']
    assert run([*docker,'image','inspect','--format','{{.Id}}',identity['imageId']],10).stdout.decode().strip()==identity['imageId']
    spec=importlib.util.spec_from_file_location('snapshot',root/'scripts/reviewer_snapshot.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
    snapshot=api.freeze(root/'reviewer-modules',root/'snapshot',identity['imageId']);pin=api.digest(snapshot)
    source_files={p.name:sha256(p.read_bytes()).hexdigest() for p in (root/'sources').iterdir()}
    write('locations-manifest.json',{'files':source_files})
    output=run([*python,str(root/'scripts/reviewer_snapshot.py'),'locations',str(root/'snapshot'),pin,str(root/'sources'),str(root/'locations-manifest.json'),'--attempts-root',str(root/'attempts')],90)
    (root/'locations.json').write_bytes(output.stdout);locations=load('locations.json')
    assert locations['reviewerExecution']['version']==3 and locations['reviewerExecution']['operation']=='locations'
    assert locations['locationBinding']['inventory']['runtimePython']=='3.12.15'
    record=api.status(Path(locations['attemptDirectory']));assert record['result']==locations
    recovered=api.recover(Path(locations['attemptDirectory']));assert recovered['result']==locations and recovered['recoveryAction']=='already-completed-no-new-receipt'
    run([node,'score.mjs','bind'])
    for arm in ('baseline','candidate'):scan(arm,arm+'-rules.json',identity)
    scanfile=root/'candidate-scan.json';binding=load('binding.json')
    write('review-manifest.json',{'files':source_files,'scanSha256':sha256(scanfile.read_bytes()).hexdigest(),'discoverImports':True,'locationBinding':locations['locationBinding']})
    write('run-start.json',{'startedAt':datetime.now(timezone.utc).isoformat()})
    output=run([*python,str(root/'scripts/reviewer_snapshot.py'),'run',str(root/'snapshot'),pin,str(root/'sources'),str(root/'review-manifest.json'),str(scanfile),binding['datasetSha256'],binding['freezeSha256'],'--attempts-root',str(root/'attempts')],90)
    (root/'execution.json').write_bytes(output.stdout);review=load('execution.json')
    assert review['reviewerExecution']['operation']=='review' and review['locationBinding']==locations['locationBinding']
    assert api.status(Path(review['attemptDirectory']))['result']==review
    assert api.recover(Path(review['attemptDirectory']))['result']==review
    assert review['reviewArtifact']['scanJson']==scanfile.read_bytes().decode()
    assert review['reviewArtifact']['manifestJson']==(root/'review-manifest.json').read_bytes().decode()
    run([node,'score.mjs','score'])
    output=run([node,'scripts/review_quality_gate.mjs','diagnostic-dataset.json','diagnostic-run.json','diagnostic-freeze.json','policy.json','ledger.json'],codes=(2,));(root/'vm-quality-cli.json').write_bytes(output.stdout)
    assert load('vm-quality-cli.json')==load('vm-quality.json')
    # Run source-only synthetic mapping cases in the exact parser image, not the guest/Mac parser.
    output=run([*docker,'run','--rm','--pull','never','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--memory-swap','256m','--cpus','1','--pids-limit','32','--log-driver','none','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777','--mount',f'type=bind,src={root},dst=/acceptance,readonly','--entrypoint','python3',identity['imageId'],'-I','-B','/acceptance/scripts/eval_locations.test.py'],45)
    (root/'fixed-image-tests.txt').write_bytes(output.stdout+output.stderr)
    output=run([node,'--test','work/harness-purge-improved/tests/review-locations-v3.test.mjs','work/harness-purge-improved/tests/review-quality-gate.test.mjs']);(root/'gate-tests.txt').write_bytes(output.stdout)
    run([node,'managed-live.mjs'])
    after=identify();assert before==after
    assert all(sha256((root/n).read_bytes()).hexdigest()==h for n,h in payload['checks'].items())
    names=['locations-manifest.json','locations.json','review-manifest.json','execution.json','binding.json','diagnostic-dataset.json','diagnostic-freeze.json','diagnostic-run.json','vm-quality.json','vm-quality-cli.json','case-evidence.json','baseline-scan.json','candidate-scan.json','snapshot/snapshot.json','fixed-image-tests.txt','gate-tests.txt','scanner-identity.json','policy.json','ledger.json','managed-live.json']
    artifacts={n:(root/n).read_text() for n in names}
    result={'inputSha256':sha256((root/'input.json').read_bytes()).hexdigest(),'sourcesVerified':payload['checks'],'dailyProgramFilesMatched':len(before['program']),'dailyDatabasesLogicallyMatched':len(before['databases']),'dailyProtection':{k:{'beforeSha256':sha256(json.dumps(v,sort_keys=True).encode()).hexdigest(),'afterSha256':sha256(json.dumps(after[k],sort_keys=True).encode()).hexdigest()} for k,v in before.items()},'artifacts':artifacts,'artifactSha256':{n:sha256(v.encode()).hexdigest() for n,v in artifacts.items()}}
    write('result.json',result);write('status.json',{'state':'completed','resultSha256':sha256((root/'result.json').read_bytes()).hexdigest()})

if __name__=='__main__':
    write('status.json',{'state':'running'})
    try:main()
    except Exception:
        write('status.json',{'state':'failed','trace':traceback.format_exc()[-3200:]});raise
