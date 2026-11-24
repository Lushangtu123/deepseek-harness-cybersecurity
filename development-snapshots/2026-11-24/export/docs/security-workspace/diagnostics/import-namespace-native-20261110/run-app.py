"""Supervise the test web app and socket service inside the private namespace."""
from pathlib import Path
import json
import os
import re
import signal
import subprocess
import sys
import time

root = Path(sys.argv[1])
settings = json.loads((root / 'stage.json').read_text())
assert os.getuid() == 1000
assert (Path('/home/purge/.dsh-improved') / 'owned-test-state').read_text() == root.name
env = {**os.environ, 'DSH_HOME': '/home/purge/.dsh-improved',
       'PATH': '/home/purge/.local/node/bin:/home/purge/.local/bin:' + os.environ['PATH'],
       'HTTP_PROXY': 'http://10.0.2.100:3128', 'HTTPS_PROXY': 'http://10.0.2.100:3128',
       'http_proxy': 'http://10.0.2.100:3128', 'https_proxy': 'http://10.0.2.100:3128',
       'NO_PROXY': 'localhost,127.0.0.1,::1,10.0.2.15', 'no_proxy': 'localhost,127.0.0.1,::1,10.0.2.15',
       'NODE_USE_ENV_PROXY': '1',
       'REDTEAM_HOME': '/home/purge/.dsh-improved/redteam'}
children = []
stopping = False
def stop(*args):
    global stopping
    stopping = True
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    with (root / 'security.log').open('w') as security_log, (root / 'web.log').open('w') as web_log:
        children.append(subprocess.Popen(['python3', '-B', str(root / 'activate-security.py'), str(root)], env=env, stdout=security_log, stderr=security_log))
        for _ in range(80):
            if Path('/run/user/1000/harness-security.sock').exists():
                break
            if children[0].poll() is not None:
                raise RuntimeError('Candidate service stopped before readiness')
            time.sleep(.1)
        assert Path('/run/user/1000/harness-security.sock').exists(),'Candidate socket did not become ready'
        children.append(subprocess.Popen(['/home/purge/.local/node/bin/node',
            '/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js', '--profile', 'web',
            '--host', '127.0.0.1', '--port', str(settings['port']), '--no-open'],
            cwd=root / 'workspace/synthetic-project', env=env, stdout=web_log, stderr=web_log))
        started = time.monotonic()
        ready = False
        while not stopping and time.monotonic() - started < 1200:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('Candidate native app stopped unexpectedly')
            if not ready:
                match = re.search(r'http://127\.0\.0\.1:' + str(settings['port']) + r'/\?token=[A-Za-z0-9_-]+', (root / 'web.log').read_text())
                if match and (root/'fence-ready.json').is_file():
                    (root / 'native-access.private').write_text(match.group(0))
                    (root / 'native-access.private').chmod(0o600)
                    (root / 'app-ready.json').write_text(json.dumps({'ready': True, 'port': settings['port'], 'namespacePID': os.getpid()}))
                    ready = True
            time.sleep(.25)
finally:
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    for child in reversed(children):
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
    (root / 'app-stopped.json').write_text(json.dumps({'childrenExited': [c.returncode for c in children]}))
