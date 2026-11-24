from pathlib import Path
import base64, importlib.util, json

here=Path(__file__).resolve().parent
release=here
repo=here.parents[1]/'exports/deepseek-harness-vm'
archive=base64.b64encode((release/'harness-vm-candidate.tar.gz').read_bytes()).decode()
expected=json.loads((release/'archive.json').read_text())
old=json.loads((here/'baseline.json').read_text())['program']
new=json.loads((repo/'work/harness-purge-improved/package-files.json').read_text());baseline=json.loads((here/'baseline.json').read_text())
source=f'ARCHIVE={archive!r}\nEXPECTED={expected!r}\nOLD={old!r}\nNEW={new!r}\nBASELINE={baseline!r}\n'+r'''
from pathlib import Path, PurePosixPath
import base64,hashlib,http.client,io,json,os,re,sqlite3,subprocess,tarfile,time
from http.cookies import SimpleCookie

home=Path('/home/purge')
assert Path.home()==home and os.getuid()==1000
package=home/'tools/dsh-purge-personal-1.1.77-personal.1'
backup=home/'.cache/harness-source-location-release-20261103'
assert not backup.exists() and package.resolve()==package
def digest(raw):return hashlib.sha256(raw).hexdigest()
def inventory(root):
    return {str(p.relative_to(root)):digest(p.read_bytes()) for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts}
def system(action,unit,check=True):
    return subprocess.run(['systemctl','--user',action,unit],env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},
                          capture_output=True,text=True,check=check,timeout=30)
def active(unit):return system('is-active',unit,False).returncode==0
def docker(*args):
    return subprocess.check_output(['/usr/bin/sudo','-n','/usr/bin/docker',*args],text=True,timeout=10).splitlines()
def assert_idle():
    for file in (home/'.dsh-improved/redteam/engagements').glob('*/assets.db'):
        with sqlite3.connect(file.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('security_run','security_joint'):
                if table in tables:
                    assert db.execute("SELECT COUNT(*) FROM "+table+" WHERE state IN ('running','cancelling')").fetchone()[0]==0
            if 'security_joint_pending' in tables:assert db.execute('SELECT COUNT(*) FROM security_joint_pending').fetchone()[0]==0
    for label in ('personal.harness.security=true','personal.harness.joint','personal.harness.runtime'):
        assert not docker('ps','-aq','--filter','label='+label)
    assert not docker('network','ls','-q','--filter','label=personal.harness.runtime')
    assert not any(n.startswith('pentagi-terminal-') for n in docker('ps','--format','{{.Names}}'))
    assert not list((home/'.dsh-improved/security-runtime-links').glob('*.json'))
def watched_raw():
    files=sorted((home/'.dsh-improved/redteam/engagements').glob('*/assets.db'))
    files += [home/name for name in ['.dsh-improved/cordis.patch.yml','.dsh-improved/.credentials.yaml','tools/security-workbench/images.json','tools/security-workbench/rules.json','.dsh-improved/profiles/web/cordis.patch.yml','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket'] if (home/name).is_file()]
    result={}
    for path in files:
        with path.open('rb') as stream:result[str(path)]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result
def watched():
    files=sorted((home/'.dsh-improved/redteam/engagements').glob('*/assets.db'))
    result={}
    for path in files:
        digest=hashlib.sha256()
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)
        try:
            for statement in db.iterdump():digest.update((statement+'\n').encode())
        finally:db.close()
        result[str(path)]=digest.hexdigest()
    for path in [home/name for name in ['.dsh-improved/cordis.patch.yml','.dsh-improved/.credentials.yaml','tools/security-workbench/images.json','tools/security-workbench/rules.json','.dsh-improved/profiles/web/cordis.patch.yml','.config/systemd/user/harness-security.service','.config/systemd/user/harness-security.socket'] if (home/name).is_file()]:
        result[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result
units=['dsh-original.service','harness-security.socket','harness-security.service']
assert inventory(package)==OLD
before_watched=watched();assert before_watched==BASELINE['watched']
raw_before=watched_raw()
assert_idle()
was={unit:active(unit) for unit in units}
assert was[units[0]]
raw=base64.b64decode(ARCHIVE);assert digest(raw)==EXPECTED['archiveSha256']
backup.mkdir(mode=0o700);assert backup.stat().st_dev==package.stat().st_dev
(backup/'protected-before.json').write_text(json.dumps({'logical':before_watched,'raw':raw_before}))
stage=backup/'candidate';stage.mkdir(mode=0o755)
previous=backup/'previous'
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    seen=set()
    for member in archive:
        name=member.name; rel=PurePosixPath(name)
        assert member.isfile() and name in NEW and name not in seen and not rel.is_absolute() and '..' not in rel.parts
        path=stage/rel;path.parent.mkdir(parents=True,exist_ok=True)
        data=archive.extractfile(member).read();assert digest(data)==NEW[name]
        path.write_bytes(data);path.chmod(member.mode & 0o755);seen.add(name)
assert inventory(stage)==NEW
node=home/'.local/node/bin/node'
subprocess.run([node,'--check',stage/'client.js'],timeout=12,check=True)
def record(phase):
    temporary=backup/'state.tmp'
    temporary.write_text(json.dumps({'phase':phase,'archiveSha256':EXPECTED['archiveSha256'],'servicesWereActive':was}))
    temporary.chmod(0o600);temporary.replace(backup/'state.json')
def stop():
    for unit in (units[1],units[2],units[0]):system('stop',unit)
def start():
    for unit in units:
        if was[unit]:system('start',unit)
    assert active(units[0])
def healthy():
    pid=system('show','dsh-original.service')
    current=re.search(r'^MainPID=([1-9][0-9]*)$',pid.stdout,re.M)
    if not current:return False
    logs=subprocess.run(['journalctl','--user','-u','dsh-original','_PID='+current[1],'-n','45','--no-pager','-o','cat'],
        env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/1000'},capture_output=True,text=True,timeout=4,check=True).stdout
    keys=re.findall(r'http://127\.0\.0\.1:49224/\?token=([A-Za-z0-9_-]+)',logs)
    if not keys:return False
    connection=http.client.HTTPConnection('10.0.2.15',3080,timeout=3)
    try:
        connection.request('GET','/?token='+keys[-1],headers={'Host':'127.0.0.1:49224'})
        response=connection.getresponse()
        cookies=SimpleCookie()
        for name,value in response.getheaders():
            if name.lower()=='set-cookie':cookies.load(value)
        response.read(2*1024*1024)
        if not cookies:return False
        connection.request('GET','/dsh-purge/status',headers={'Host':'127.0.0.1:49224',
            'Cookie':'; '.join(name+'='+value.value for name,value in cookies.items())})
        response=connection.getresponse()
        value=json.loads(response.read(1024*1024))
        return response.status==200 and value.get('ok') is True and value.get('ready') is True
    finally:connection.close()
def wait_healthy():
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            if healthy():return
        except (OSError,ValueError,subprocess.SubprocessError,http.client.HTTPException):pass
        time.sleep(0.5)
    raise RuntimeError('Authenticated candidate health check failed')
record('prepared')
try:
    stop()
    assert_idle()
    raw_stopped=watched_raw()
    (backup/'protected-stopped.json').write_text(json.dumps({'logical':watched(),'raw':raw_stopped}))
    assert inventory(package)==OLD and watched()==before_watched
    package.rename(previous)
    record('previous-retained')
    stage.rename(package)
    record('candidate-in-place')
    assert inventory(package)==NEW
    start()
    wait_healthy()
    assert watched()==before_watched
    record('candidate-service-active')
except BaseException:
    if previous.exists():
        stop()
        if package.exists():
            assert inventory(package)==NEW
            package.rename(stage)
        previous.rename(package)
    assert inventory(package)==OLD
    start()
    record('rolled-back')
    raise
print(json.dumps({'programFiles':len(NEW),'rollbackFiles':len(OLD),'servicesRestarted':was,
                  'protectedFileDigestsMatched':len(before_watched),'archiveSha256':EXPECTED['archiveSha256'],
                  'backup':str(backup),'candidateServiceActive':True,'databaseProtection':'logical dump; other protected files byte digest','physicalProtectedFilesChangedAfterStop':sum(raw_stopped.get(k)!=v for k,v in raw_before.items())}))
'''
host=Path.home()/'Library/Application Support/Harness Purge Original'
spec=importlib.util.spec_from_file_location('manager',host/'host-tools/manage.py')
manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
manager.validate()
with manager.vm_operation('switch'):
    result=json.loads(manager.ssh('python3 -B -',input=source,timeout=175,phase='program-update').stdout)
    (here/'deploy.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
