"""Guest-only file transaction, also exercised with temporary paths in tests."""
import json
import os
import shlex
import subprocess
from pathlib import Path


def atomic_write(path, data, mode):
    temp = path.with_suffix(path.suffix + '.tmp')
    try:
        temp.write_bytes(data)
        temp.chmod(mode)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def install(root, profile, original, command, payload, restart):
    root.mkdir(parents=True, exist_ok=True)
    original_bytes = original.read_bytes()
    targets = [*(root / name for name in payload), profile, command, root / 'cordis-before-toolchain.yml']
    before = {}
    for target in targets:
        if target.is_symlink():
            raise RuntimeError('Installer refuses symbolic link targets')
        before[target] = (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
    try:
        for name, source in payload.items():
            atomic_write(root / name, source.encode(), 0o644)
        cli = '#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(root / 'check_versions.py')) + ' "$@"\n'
        atomic_write(command, cli.encode(), 0o755)
        text = profile.read_text()
        if 'id: personal-toolchain-versions' not in text:
            backup = root / 'cordis-before-toolchain.yml'
            if not backup.exists():
                atomic_write(backup, text.encode(), 0o600)
            text += ('\n- insert:\n    - id: personal-toolchain-versions\n      name: '
                     + json.dumps(str(root / 'index.mjs')) + '\n')
            atomic_write(profile, text.encode(), before[profile][1])
        assert original.read_bytes() == original_bytes, 'Original profile changed'
        restart()
    except BaseException as error:
        failures = []
        for target, snapshot in before.items():
            try:
                if snapshot is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, *snapshot)
            except BaseException as rollback_error:
                failures.append(str(rollback_error))
        try:
            restart()
        except BaseException as rollback_error:
            failures.append(str(rollback_error))
        if failures:
            raise RuntimeError('Installation failed and rollback needs inspection: ' + '; '.join(failures)) from error
        raise
    return {'installed': True, 'files': list(payload), 'nativeTool': 'toolchain_versions_check',
            'command': str(command), 'originalProfileUnchanged': original.read_bytes() == original_bytes}


def restart_service():
    env = {**os.environ, 'XDG_RUNTIME_DIR': '/run/user/1000'}
    # Service TimeoutStopSec is 30s. Bound a complete stop/start, then allow
    # another complete budget for rollback before the host SSH deadline.
    subprocess.run(['systemctl', '--user', 'restart', 'dsh-original'], env=env, check=True, timeout=40)
    subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'dsh-original'], env=env, check=True, timeout=5)


def main(payload):
    print(json.dumps(install(Path('/home/purge/.dsh-improved/tooling/toolchain-version-checker'),
          Path('/home/purge/.dsh-improved/cordis.patch.yml'), Path('/home/purge/.dsh/cordis.patch.yml'),
          Path('/home/purge/.local/bin/toolchain-versions'), payload, restart_service)))
