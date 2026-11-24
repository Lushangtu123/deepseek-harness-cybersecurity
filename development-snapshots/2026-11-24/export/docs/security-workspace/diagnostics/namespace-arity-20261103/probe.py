"""Execute only fixed authored arithmetic controls inside the isolated guest container."""
from pathlib import Path
from hashlib import sha256
import errno, importlib.util, json, os, sys

assert sys.platform == 'linux' and os.geteuid() == 65534 and Path('/.dockerenv').is_file()
plan = json.loads(Path('/protocol.json').read_text())
digest = lambda p: sha256(Path(p).read_bytes()).hexdigest()
assert digest('/probe.py') == plan['probeSha256']
status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert status['CapEff'].strip() == '0000000000000000' and status['NoNewPrivs'].strip() == '1' and status['Seccomp'].strip() == '2'
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == '268435456'
assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '32'
assert set(os.listdir('/sys/class/net')) == {'lo'}
assert all(not Path(p).exists() for p in ['/home/purge/.ssh','/home/purge/.dsh-improved','/var/run/docker.sock'])
for directory in ['/src','/']:
    try:
        Path(directory,'DIAGNOSTIC_NO_WRITE').write_text('x')
        raise AssertionError('Input writable')
    except OSError as error:
        assert error.errno == errno.EROFS

modules = {}
for name, expected in plan['sources'].items():
    path = Path('/src') / name
    assert path.name == name and digest(path) == expected
    spec = importlib.util.spec_from_file_location(name[:-3].replace('-','_'),path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    modules[name[:-3]] = module

observations = []
for vector in plan['vectors']:
    module = modules[vector['caseId']]
    filename = module.run.__code__.co_filename
    path = Path(filename)
    assert str(path.parent) == '/src' and digest(path) == plan['sources'][path.name]
    assert all(value is None or type(value) in [str,bool] for value in vector['args'])
    assert all(len(value) <= 512 for value in vector['args'] if type(value) is str)
    frames = []
    def trace(frame,event,arg):
        caller = frame.f_back
        if event == 'call' and frame.f_code.co_filename == '<string>' and caller and caller.f_code.co_filename == filename:
            frames.append({'line':caller.f_lineno, 'function':caller.f_code.co_name,
                           'codeNames':list(frame.f_code.co_names),
                           'constants':[v for v in frame.f_code.co_consts if type(v) in [int,str,type(None)]],
                           'compiledFilename':frame.f_code.co_filename})
        return trace
    sys.settrace(trace)
    try:
        try:
            value = module.run(*vector['args'])
            error = None
        except ValueError:
            value = None
            error = 'ValueError'
    finally:
        sys.settrace(None)
    assert len(frames) == vector['dynamicFrames'], (vector,frames)
    if 'error' in vector:
        assert error == vector['error'] and value is None
    else:
        assert error is None and type(value) is type(vector['expected']) and value == vector['expected'], (vector,value,error)
    observations.append({'id':vector['id'], 'caseId':vector['caseId'],
                         'sourceSha256':digest(path), 'arguments':vector['args'],
                         'result':value, 'error':error, 'dynamicFrames':frames,
                         'role':'authored-runtime-diagnostic', 'qualifiesForR3':False})

listeners = sum(1 for name in ['tcp','tcp6'] if (p:=Path('/proc/net')/name).exists()
                for line in p.read_text().splitlines()[1:] if line.split()[3]=='0A')
assert listeners == 0
print(json.dumps({'ok':True, 'python':sys.version.split()[0],
                  'probeSha256':digest('/probe.py'), 'protocolSha256':digest('/protocol.json'),
                  'sourceIdentityMatched':True,
                  'conditions':{'uid':os.geteuid(),'networkInterfaces':['lo'],'tcpListenersAfter':listeners,
                                'readonlyFailuresRequired':'EROFS','plainStringsAndFixedArithmeticOnly':True},
                  'observations':observations, 'independentCases':0,'qualifiesForR3':False,
                  'noHttpOrVulnerabilityConfirmationClaim':True}))
