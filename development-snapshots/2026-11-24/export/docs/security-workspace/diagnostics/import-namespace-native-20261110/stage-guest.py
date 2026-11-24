from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from hashlib import sha256
import base64, gzip, json, os, re, signal, socket, sqlite3, subprocess, time, yaml

os.umask(0o077)
home=Path('/home/purge');daily=home/'.dsh-improved'
installed=home/'tools/dsh-purge-personal-1.1.77-personal.1'
runtime=home/'tools/harness-improved-runtime/node_modules'
def digest(path):return sha256(path.read_bytes()).hexdigest()
def identity():
    databases={}
    for p in (daily/'redteam/engagements').glob('*/assets.db'):
        value=sha256()
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            for row in db.iterdump():value.update((row+'\n').encode())
        databases[str(p)]=value.hexdigest()
    return {'program':{str(p.relative_to(installed)):digest(p) for p in installed.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts},
            'config':{str(p):digest(p) for p in [daily/'.credentials.yaml',daily/'cordis.patch.yml',
                 daily/'profiles/web/package.json',daily/'profiles/web/cordis.patch.yml']},
            'pins':{name:digest(home/'tools/security-workbench'/name) for name in ['images.json','rules.json']},
            'runtime':digest(runtime/'@deepseek-ai/dsh-tools/lib/index.js'),'databases':databases,
            'outsideMountNamespace':os.readlink('/proc/self/ns/mnt'),'homeInode':daily.stat().st_ino}
before=identity();assert len(before['program'])==169
data=json.loads(gzip.decompress(base64.b64decode(PAYLOAD,validate=True)))
root=Path(mkdtemp(prefix='score-native-qa-',dir=home/'.cache'))
child=None
try:
    (root/'protected.json').write_text(json.dumps(before))
    for name,encoded in data['files'].items():
        rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(base64.b64decode(encoded,validate=True));assert digest(p)==data['hashes'][name]
        if name=='package/scripts/python_namespace_review.py':p.chmod(0o644)
    (root/'package/node_modules').symlink_to(runtime,target_is_directory=True)
    result=subprocess.run(['/home/purge/.local/node/bin/node',str(root/'seed.mjs')],cwd=root,
                          capture_output=True,text=True,timeout=20)
    if result.returncode:raise RuntimeError('Owned synthetic seed failed: '+result.stderr[-1200:])
    fixture=json.loads(result.stdout);assert fixture['newScannerCalls']==0
    temp=root/'home';profile=temp/'profiles/web'
    for p in [profile/'node_modules',temp/'storages',temp/'dsh-purge',temp/'redteam',root/'run']:
        p.mkdir(parents=True,exist_ok=True)
    (temp/'owned-test-state').write_text(root.name)
    (profile/'node_modules/@deepseek-ai').symlink_to(runtime/'@deepseek-ai',target_is_directory=True)
    (profile/'node_modules/dsh-purge').symlink_to(root/'package',target_is_directory=True)
    (profile/'package.json').write_text(json.dumps({'name':'dsh-profile-web','private':True,
        'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','dsh-purge']}}}))
    (profile/'cordis.yml').write_text('[]\n')
    credentials=yaml.safe_load((daily/'.credentials.yaml').read_text())
    key=credentials.get('refs',{}).get('DEEPSEEK_API_KEY');assert isinstance(key,str) and len(key)>16
    (temp/'.credentials.yaml').write_text(json.dumps({'version':1,'refs':{'DEEPSEEK_API_KEY':key},'records':{}}))
    grant=daily/'dsh-purge/drill-grant.json'
    if grant.is_file() and json.loads(grant.read_text()).get('granted') is True:
        (temp/'dsh-purge/drill-grant.json').write_bytes(grant.read_bytes())
    patch=[{'id':'session-log-deepseek','config':{'enabled':False}},
      {'id':'session-telemetry-otel','disabled':True},{'id':'product-analytics','config':{'enabled':False}},
      {'id':'sandbox-policy','config':{'mode':'danger-full-access'}},
      {'id':'approval','config':{'policy':'never'}},
      {'id':'permission','config':{'defaultPreset':'danger-full-access'}},
      {'id':'agent-default-model','config':{'provider':'deepseek-official','model':'deepseek-flash'}},
      {'id':'agent','config':{'provider':'deepseek-official','model':'deepseek-flash'}},
      {'id':'dsh-purge','config':{'enabled':True,'autoApplyOnStart':False,'autoUpdateOnStart':False,'executionMode':'vm-autonomous'}},
      {'id':'agent-preset-registry','config':{'default':'personal-joint'}},
      {'insert':[{'id':'personal-joint','name':'dsh-purge/personal-joint'},
        {'id':'qa-native-fence','name':str(root/'qa-fence.mjs'),'config':{'root':str(root),'engagement':fixture['engagement']}}]}]
    (temp/'cordis.patch.yml').write_text(yaml.safe_dump(patch,allow_unicode=True))
    web=[{'id':'ui-theme','config':{'preference':'light'}},
      {'id':'ui-settings-general','config':{'welcomeNoticeVersion':'2026-09-28.1'}},
      {'id':'ui-settings-account','config':{'version':1,'step':'done','usage':'detailed','developerTools':True,
        'purpose':None,'process':'standard','completion':'api-key'}}]
    (profile/'cordis.patch.yml').write_text(yaml.safe_dump(web,allow_unicode=True))
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    stage={'root':str(root),'port':port,'engagement':fixture['engagement'],'fixture':fixture,
        'programFiles':173,'programDigest':data['programDigest'],'outsideMountNamespace':before['outsideMountNamespace'],
        'workerMode':oct((root/'package/scripts/python_namespace_review.py').stat().st_mode&0o777),
        'profilePackagePhysicalPath':str((profile/'node_modules/dsh-purge').resolve()),'runtimeTree':str(runtime)}
    (root/'stage.json').write_text(json.dumps(stage));(root/'intent.json').write_text(json.dumps(data['hashes']))
    with (root/'namespace.log').open('wb') as log:
        child=subprocess.Popen(['/usr/bin/sudo','-n','/usr/bin/unshare','--mount','--pid','--fork',
           '--mount-proc','--kill-child=SIGKILL','--propagation','private','/usr/bin/python3','-I','-B',
           str(root/'namespace-init.py'),str(root)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,
           start_new_session=True,close_fds=True)
    stage['supervisorPID']=child.pid;(root/'stage.json').write_text(json.dumps(stage))
    for _ in range(160):
        if (root/'app-ready.json').is_file():
            assert identity()==before
            assert all(digest(root/name)==want for name,want in data['hashes'].items())
            stage.update(ready=True,productionUnchanged=True,fence=json.loads((root/'fence-ready.json').read_text()))
            print(json.dumps(stage));break
        if child.poll() is not None:raise RuntimeError('Namespace supervisor exited')
        time.sleep(.2)
    else:raise RuntimeError('Native readiness timeout')
except Exception as error:
    if child is not None and child.poll() is None:os.killpg(child.pid,signal.SIGTERM)
    diagnostics={}
    for name in ['namespace.log','web.log','security.log']:
        p=root/name
        if p.is_file():
            raw=p.read_text()[-2400:]
            if 'key' in locals():raw=raw.replace(key,'[redacted]')
            diagnostics[name]=re.sub(r'(token=|sk-)[A-Za-z0-9_-]{12,}',r'\1[redacted]',raw)
    print(json.dumps({'ready':False,'root':str(root),'supervisorPID':child.pid if child else None,
        'error':str(error),'diagnostics':diagnostics}))
