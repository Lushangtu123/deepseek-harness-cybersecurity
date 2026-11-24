"""Private mount/PID namespace setup. Parent VM mounts remain untouched."""
from pathlib import Path
import json
import os
import subprocess
import sys

root = Path(sys.argv[1])
settings = json.loads((root / 'stage.json').read_text())
assert os.getpid() == 1 and os.getuid() == 0
assert os.readlink('/proc/self/ns/mnt') != settings['outsideMountNamespace']
subprocess.run(['/usr/bin/mount', '--make-rprivate', '/'], check=True)
def bind(source, target, readonly=False):
    subprocess.run(['/usr/bin/mount', '--bind', str(source), str(target)], check=True)
    if readonly:
        subprocess.run(['/usr/bin/mount', '-o', 'remount,bind,ro', str(target)], check=True)
bind(root / 'home', '/home/purge/.dsh-improved')
bind(root / 'state', '/home/purge/.dsh-improved/redteam')
bind(root / 'package', '/home/purge/tools/dsh-purge-personal-1.1.77-personal.1', True)
bind(root / 'run', '/run/user/1000')
raise SystemExit(subprocess.run(['/usr/sbin/runuser', '-u', 'purge', '--', 'python3', '-B', str(root / 'run-app.py'), str(root)]).returncode)
