"""Inspect literal mentions in explicit DSH files; never output config values.

No traversal, YAML/JS evaluation, process launch or MCP handshake. This is a
bounded diagnostic, not a sandbox against concurrent filesystem changes.
"""
from pathlib import Path
import argparse
import json
import os
import re
import stat

MAX_BYTES = 1024 * 1024
PROFILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def inspect_file(home, relative):
    path = home / relative
    row = {'path': str(path), 'state': 'missing', 'codegraph_literal_present': None}
    current = home
    try:
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                row['state'] = 'blocked_symlink'; return row
        if not stat.S_ISREG(info.st_mode):
            row['state'] = 'not_regular_file'; return row
        if info.st_size > MAX_BYTES:
            row['state'] = 'too_large'; return row
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                row['state'] = 'not_regular_file'; return row
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            row['state'] = 'too_large'; return row
        text = data.decode('utf-8')
        if '\0' in text:
            row['state'] = 'not_text'; return row
        row.update(state='read', codegraph_literal_present='codegraph' in text.casefold())
    except FileNotFoundError:
        pass
    except UnicodeDecodeError:
        row['state'] = 'not_utf8'
    except OSError:
        row['state'] = 'unreadable'
    return row


def inspect_home(home, profile=None):
    home = Path(home).expanduser().absolute()
    if home.is_symlink() or not home.is_dir():
        raise ValueError('Select an existing non-symlink DSH home directory')
    if profile is not None and not PROFILE.fullmatch(profile):
        raise ValueError('Select one profile name, without dots or path separators')
    paths = [Path('cordis.patch.yml')]
    if profile is not None:
        paths += [Path('profiles') / profile / name for name in ('cordis.yml', 'cordis.patch.yml')]
    return {'home': str(home), 'profile': profile,
        'files': [inspect_file(home, path) for path in paths],
        'interpretation': 'literal_presence_only_not_registration', 'connection': 'unverified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh-home', required=True)
    parser.add_argument('--profile', help='Actual active profile; omit if unknown')
    args = parser.parse_args()
    try:
        result = inspect_home(args.dsh_home, args.profile)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
