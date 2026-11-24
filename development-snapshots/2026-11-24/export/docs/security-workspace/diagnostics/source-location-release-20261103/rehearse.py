"""Check a full candidate and reversible directory switch in the dedicated VM."""
from pathlib import Path
import base64
import importlib.util
import json

work = Path(__file__).resolve().parent
repo = work.parents[1] / 'exports/deepseek-harness-vm'
inventory = json.loads((repo/'work/harness-purge-improved/package-files.json').read_text())
archive = base64.b64encode((work/'harness-vm-candidate.tar.gz').read_bytes()).decode()
expected = json.loads((work/'archive.json').read_text())
baseline = {'programFiles': 165, 'programDigest': '65160e479acfb04bffe71aeb8b05ce8175008d7531d8f70f5572692dfaf34a41', 'scannerManifestSha256': '6a3a04e4f0f81aaa77e4f312eb6cb90a28ebc75c6e0b1ee06b214dc48195c36c'}
source = f'ARCHIVE={archive!r}\nINVENTORY={inventory!r}\nRELEASE={expected!r}\nBASELINE={baseline!r}\n' + '''
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import base64,hashlib,io,json,os,shutil,subprocess,tarfile

def digest(data):
    return hashlib.sha256(data).hexdigest()

def files(root):
    return {str(path.relative_to(root)):digest(path.read_bytes()) for path in sorted(root.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts}

home=Path('/home/purge')
daily=home/'tools/dsh-purge-personal-1.1.77-personal.1'
manifest=home/'tools/security-workbench/images.json'
deployed=files(daily)
assert len(deployed)==BASELINE['programFiles']
assert digest(json.dumps(deployed,sort_keys=True).encode())==BASELINE['programDigest']
assert digest(manifest.read_bytes())==BASELINE['scannerManifestSha256']
env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'}
def service():
    return subprocess.check_output(['systemctl','--user','show','dsh-original','-p','MainPID','--value'],
                                   env=env,text=True,timeout=8).strip()
pid=service()
assert int(pid)>0
def active_scanners():
    return subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker','ps','-q','--filter',
                                    'label=personal.harness.security=true'],text=True,timeout=8).splitlines()
before_active=len(active_scanners())
raw=base64.b64decode(ARCHIVE)
assert digest(raw)==RELEASE['archiveSha256']
with TemporaryDirectory(prefix='candidate-release-',dir=home/'.cache') as directory:
    stage=Path(directory)
    candidate=stage/'candidate'
    candidate.mkdir()
    extracted=set()
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as package:
        for member in package:
            name=member.name
            relative=PurePosixPath(name)
            assert member.isfile() and not relative.is_absolute() and '..' not in relative.parts
            assert name in INVENTORY and name not in extracted and 0<=member.size<=8*1024*1024
            target=candidate/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            payload=package.extractfile(member).read()
            assert digest(payload)==INVENTORY[name]
            target.write_bytes(payload)
            target.chmod(member.mode & 0o755)
            extracted.add(name)
    assert files(candidate)==INVENTORY
    node=home/'.local/node/bin/node'
    subprocess.run([node,'--check',candidate/'client.js'],timeout=10,check=True)
    p=subprocess.run([node,candidate/'scripts/security-runtime-preflight.mjs'],
                     capture_output=True,text=True,timeout=35)
    runtime=json.loads(p.stdout)
    assert p.returncode==0 and runtime['readOnly'] and not runtime['automaticChanges'] and all(row.get('ready') is True for row in runtime['tools'].values())
    # Rehearse only on a same-filesystem copy. The live directory is never renamed.
    active=stage/'active'
    backup=stage/'backup'
    shutil.copytree(daily,active,ignore=shutil.ignore_patterns('__pycache__'))
    assert files(active)==deployed
    active.rename(backup)
    candidate.rename(active)
    assert files(active)==INVENTORY
    active.rename(candidate)
    backup.rename(active)
    assert files(active)==deployed
    free=shutil.disk_usage(home).free
assert not stage.exists() and files(daily)==deployed and pid==service()
assert digest(manifest.read_bytes())==BASELINE['scannerManifestSha256']
print(json.dumps({'archiveSha256':RELEASE['archiveSha256'],'candidateFiles':len(INVENTORY),
 'currentFiles':len(deployed),'candidateSyntaxChecked':True,'temporarySwapAndRollbackVerified':True,
 'deploymentUnchanged':True,'dailyProcessUnchanged':True,'temporaryRemoved':True,
 'activeScannerContainersAtStart':before_active,'activeScannerContainersAtEnd':len(active_scanners()),
 'guestFreeBytes':free,'scannerPreflightExitCode':p.returncode,
 'scannerReadiness':{name:{'ready':row.get('ready') is True,'reason':row.get('reason')}
                     for name,row in runtime['tools'].items()}}))
'''
manager_path = Path.home()/'Library/Application Support/Harness Purge Original/host-tools/manage.py'
spec=importlib.util.spec_from_file_location('harness_manager',manager_path)
manager=importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
manager.validate()
value=json.loads(manager.ssh('python3 -B -',input=source,timeout=75,phase='native-check').stdout)
(work/'rehearsal.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
