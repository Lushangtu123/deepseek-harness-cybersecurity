#!/usr/bin/env python3
"""Read-only, fixed-origin VM toolchain version inspection. No update operations."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECTS = {'rea': 'morluto/rea', 'reverse-skill': 'zhaoxuya520/reverse-skill',
            'pentagi': 'vxcontrol/pentagi'}
PROXY = 'http://10.0.2.100:3128'
SHA = re.compile(r'^[0-9a-f]{40}$')
PROJECT_BUDGET = 18.0
_project_clock = threading.local()


def query_timeout(cap=14):
    deadline = getattr(_project_clock, 'deadline', None)
    remaining = cap if deadline is None else min(cap, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('Project inspection budget expired')
    return remaining


def clean_env():
    return {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C.UTF-8',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
            'HTTPS_PROXY': PROXY, 'HTTP_PROXY': PROXY, 'NO_PROXY': ''}


def parse_refs(text):
    result = {}
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields) != 2:
            continue
        value, ref = fields
        if ref == 'HEAD' and value.startswith('ref: refs/heads/'):
            result['defaultBranch'] = value[len('ref: refs/heads/'):]
        elif SHA.fullmatch(value):
            result[ref] = value
    return result


def query_refs(project, patterns):
    if project not in PROJECTS:
        raise ValueError('project must be rea, reverse-skill, or pentagi')
    if any(p != 'HEAD' and not p.startswith('refs/tags/') for p in patterns):
        raise ValueError('Only HEAD and release tag references are supported')
    args = ['/usr/bin/git', '-c', 'credential.helper=', '-c', 'core.askPass=',
            '-c', 'http.extraHeader=', '-c', 'protocol.file.allow=never',
            '-c', 'http.followRedirects=false', 'ls-remote', '--symref',
            'https://github.com/' + PROJECTS[project] + '.git', *patterns]
    result = subprocess.run(args, capture_output=True, text=True, timeout=query_timeout(),
                            env=clean_env(), cwd='/tmp')
    if result.returncode or len(result.stdout) > 262144:
        raise RuntimeError('GitHub references unavailable; check VM GitHub connectivity and retry.')
    return parse_refs(result.stdout)


def release_tag(repo, url):
    parsed = urlsplit(url)
    prefix = '/' + repo + '/releases/tag/'
    tag = unquote(parsed.path[len(prefix):]) if parsed.path.startswith(prefix) else ''
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or
            parsed.fragment or not tag or len(tag) > 160 or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/+-]*', tag) or '..' in tag):
        raise ValueError('Unexpected GitHub release redirect; no other origin will be contacted.')
    return tag


def latest_release(project):
    repo = PROJECTS[project]
    timeout = query_timeout()
    result = subprocess.run(['/usr/bin/curl', '-q', '--proxy', PROXY, '--noproxy', '',
                             '--proto', '=https', '--max-time', str(min(12, timeout)), '-sS', '-I',
                             'https://github.com/' + repo + '/releases/latest'],
                            capture_output=True, text=True, timeout=timeout, env=clean_env(), cwd='/tmp')
    if result.returncode == 28:
        raise TimeoutError('Release lookup timed out')
    if result.returncode or len(result.stdout) > 65536:
        return {'state': 'unavailable', 'errorCode': 'network_unavailable', 'reason': 'Release lookup failed; retry after checking GitHub connectivity.'}
    # Ignore the proxy CONNECT block. No redirect is followed and no release body is read.
    statuses = re.findall(r'^HTTP/\S+\s+(\d+)', result.stdout, re.M)
    status = int(statuses[-1]) if statuses else 0
    locations = re.findall(r'^location:\s*(.*?)\s*$', result.stdout, re.M | re.I)
    if status in (301, 302, 303, 307, 308) and locations:
        location = locations[-1]
        if location == 'https://github.com/' + repo + '/releases':
            return {'state': 'no_release'}
        try:
            tag = release_tag(repo, location)
            return {'state': 'available', 'tag': tag, 'url': location}
        except ValueError:
            return {'state': 'unavailable', 'errorCode': 'unexpected_redirect', 'reason': 'Unexpected release redirect; inspect the fixed repository manually.'}
    if status == 404:
        return {'state': 'no_release'}  # check_project requires a successful HEAD query too.
    return {'state': 'unavailable', 'errorCode': 'rate_limited' if status == 429 else 'access_denied' if status == 403 else 'network_unavailable', 'reason': 'GitHub release lookup returned HTTP ' + str(status) + '; retry later.'}


def tag_revision(refs, tag):
    return refs.get('refs/tags/' + tag + '^{}') or refs.get('refs/tags/' + tag)


def verify_files(root, files):
    changed = 0
    if not files or root.is_symlink():
        return 1
    for name, expected in files.items():
        path = root / name
        try:
            safe = path.resolve().is_relative_to(root.resolve()) and not path.is_symlink()
            if not safe or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed += 1
        except OSError:
            changed += 1
    return changed


def read_installed(project, catalog, home=Path('/home/purge')):
    record = catalog.get('projects', {}).get(project, {})
    try:
        if project == 'rea':
            root = home / 'tools/rea-runtime/node_modules/rea-agents'
            package = json.loads((root / 'package.json').read_text())
            changed = verify_files(root, catalog.get('reaFiles', {}))
            known = package.get('name') == 'rea-agents' and package.get('version') == record.get('npmVersion') and not changed
            return {'available': changed == 0, 'version': package.get('version'),
                    'revision': record.get('revision') if known else None,
                    'provenance': 'installation-record-and-package-hashes' if known else 'package-version-only',
                    'changedFiles': changed,
                    'errorCode': 'local_modified' if changed else None,
                    'note': 'npm package version; local dependency overrides are outside this comparison.'}
        if project == 'reverse-skill':
            directory = catalog['reverseDirectory']
            if not re.fullmatch(r'reverse-skill-[A-Za-z0-9]+', directory):
                raise ValueError('Invalid archive directory')
            root = home / 'tools/reverse-skill' / directory
            changed = verify_files(root, catalog.get('reverseFiles', {}))
            return {'available': changed == 0, 'revision': record.get('commit') if not changed else None,
                    'provenance': 'installation-record-and-archive-hashes', 'changedFiles': changed,
                    'errorCode': 'local_modified' if changed else None,
                    'note': 'Recorded archive source files checked; extra local files are not an upstream version.'}
        if project == 'pentagi':
            template = ('{"version":{{json (index .Config.Labels "com.pentagi.version")}},'
                        '"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
                        '"imageId":{{json .Image}}}')
            result = subprocess.run(['/usr/bin/sudo', '-n', '/usr/bin/docker', '--host',
                                     'unix:///var/run/docker.sock', 'inspect', '--format', template,
                                     'harness-pentagi-pentagi-1'], capture_output=True, text=True,
                                    timeout=5, env=clean_env(), cwd='/tmp')
            if result.returncode:
                raise RuntimeError('PentAGI container metadata unavailable; start its existing stack and retry.')
            item = json.loads(result.stdout)
            return {'available': bool(SHA.fullmatch(item.get('revision') or '')),
                    'version': item.get('version'), 'revision': item.get('revision'),
                    'errorCode': None if SHA.fullmatch(item.get('revision') or '') else 'container_metadata_unverified',
                    'imageId': item.get('imageId'), 'provenance': 'container-image-labels',
                    'note': 'Running/created container image metadata; no registry pull was performed.'}
        raise ValueError('Unsupported project')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        return {'available': False, 'revision': None,
                'errorCode': 'container_unavailable' if project == 'pentagi' else 'installation_unavailable',
                'reason': 'Installed metadata unavailable; inspect the existing installation before checking again.'}


def numeric_version(value):
    match = re.fullmatch(r'(?:v|rea-agents-)?(\d+)\.(\d+)\.(\d+)', value or '')
    return tuple(map(int, match.groups())) if match else None


def compare(installed, release, head):
    stable = development = None
    version_matches = None
    status = 'unverified'
    revision = installed.get('revision') if installed.get('available') else None
    if revision and head.get('state') == 'available':
        development = revision == head.get('revision')
    if installed.get('available') and release.get('state') == 'available':
        local_version, release_version = numeric_version(installed.get('version')), numeric_version(release.get('tag'))
        if local_version and release_version:
            version_matches = local_version == release_version
        if revision and release.get('revision'):
            stable = revision == release['revision']
        elif version_matches is False:
            stable = False
    if stable is True:
        status = 'release_matches_development_differs' if development is False else 'matches_latest_release'
    elif stable is False:
        local, remote = numeric_version(installed.get('version')), numeric_version(release.get('tag'))
        status = 'update_available' if local and remote and remote > local else 'revision_differs'
    elif release.get('state') == 'no_release' and development is not None:
        status = 'matches_default_branch_no_release' if development else 'default_branch_differs_no_release'
    elif development is not None:
        status = 'default_branch_matches_release_unverified' if development else 'default_branch_differs_release_unverified'
    return {'status': status, 'matchesLatestRelease': stable, 'matchesDefaultBranch': development,
            'releaseVersionMatches': version_matches,
            'note': 'Different commits do not prove behind/ahead. Custom builds are not ordered as stable versions.'}


def _check_project(project, catalog, installed=None, local_only=False):
    item = installed if installed is not None else read_installed(project, catalog)
    release, head = {'state': 'not_checked'}, {'state': 'not_checked'}
    timed_out = []
    if not local_only:
        try:
            refs = query_refs(project, ['HEAD'])
            if not refs.get('HEAD'):
                raise RuntimeError('Missing HEAD')
            head = {'state': 'available', 'revision': refs['HEAD'], 'branch': refs.get('defaultBranch')}
        except (TimeoutError, subprocess.TimeoutExpired):
            timed_out.append('default_branch')
            head = {'state': 'timeout', 'errorCode': 'timeout', 'reason': 'Default branch lookup timed out; other project results are retained.'}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            head = {'state': 'unavailable', 'errorCode': 'network_unavailable', 'reason': 'Default branch unavailable; check VM GitHub connectivity and retry.'}
        try:
            release = latest_release(project)
            if release['state'] == 'no_release' and head['state'] != 'available':
                release = {'state': 'unavailable', 'errorCode': 'repository_unverified', 'reason': 'Repository could not be verified; no-release status is unconfirmed.'}
            if release['state'] == 'available':
                tag = release['tag']
                refs = query_refs(project, ['refs/tags/' + tag, 'refs/tags/' + tag + '^{}'])
                release['revision'] = tag_revision(refs, tag)
                if not release['revision']:
                    release['errorCode'] = 'release_commit_unavailable'
                    release['reason'] = 'Release tag commit unavailable; matching version labels alone do not confirm a release match.'
        except (TimeoutError, subprocess.TimeoutExpired):
            timed_out.append('release')
            if release.get('state') == 'available':
                release['revision'] = None
                release['errorCode'] = 'timeout'
                release['reason'] = 'Release commit lookup timed out; matching version labels do not confirm a release match.'
            else:
                release = {'state': 'timeout', 'errorCode': 'timeout', 'reason': 'Release lookup timed out; other project results are retained.'}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            # Preserve a validated release tag while making its missing commit explicit.
            if release.get('state') == 'available':
                release['revision'] = None
                release['errorCode'] = 'release_commit_unavailable'
                release['reason'] = 'Release commit lookup failed; retry after checking GitHub connectivity.'
            else:
                release = {'state': 'unavailable', 'errorCode': 'network_unavailable', 'reason': 'Release lookup failed; retry after checking GitHub connectivity.'}
    return {'project': project, 'repository': 'https://github.com/' + PROJECTS[project],
            'checkedAt': datetime.now(timezone.utc).isoformat(),
            'installed': item, 'latestRelease': release, 'defaultBranch': head,
            'queryState': 'local_only' if local_only else 'timeout' if timed_out else 'completed',
            'timedOutStages': timed_out,
            'comparison': compare(item, release, head)}


def check_project(project, catalog, installed=None, local_only=False):
    previous = getattr(_project_clock, 'deadline', None)
    # Stop cooperative lookups before the parent hard limit so partial fields
    # can be serialized and cleanup can finish. Blocked local I/O is hard-killed.
    _project_clock.deadline = time.monotonic() + PROJECT_BUDGET - min(3.0, PROJECT_BUDGET * .2)
    try:
        return _check_project(project, catalog, installed, local_only)
    finally:
        _project_clock.deadline = previous


def failed_project(name, timed_out=False):
    state = 'timeout' if timed_out else 'unavailable'
    item = {'available': False, 'errorCode': 'timeout' if timed_out else 'installation_unavailable', 'reason': 'Local version inspection did not finish; no version match is confirmed.'}
    release = {'state': state, 'errorCode': 'timeout' if timed_out else 'inspection_failed', 'reason': 'Project inspection timed out; other completed projects are retained.' if timed_out else 'Project inspection failed; inspect its installation and retry.'}
    head = dict(release)
    return {'project': name, 'repository': 'https://github.com/' + PROJECTS[name],
            'checkedAt': datetime.now(timezone.utc).isoformat(),
            'installed': item, 'latestRelease': release, 'defaultBranch': head,
            'queryState': 'timeout' if timed_out else 'failed',
            'timedOutStages': ['project'] if timed_out else [], 'comparison': compare(item, release, head)}


def worker_command(name, local_only):
    if name not in PROJECTS:
        raise ValueError('Unsupported project')
    return [sys.executable, '-B', str(Path(__file__).resolve()), '--project', name,
            '--inspect-one', '--json', *(['--local-only'] if local_only else [])]


class ProjectRunner:
    """Own/reap per-project process groups, including hung local file readers."""
    def __init__(self):
        self.lock = threading.Lock()
        self.processes = set()
        self.cancelled = False

    @staticmethod
    def kill(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def stop(self):
        with self.lock:
            self.cancelled = True
            processes = list(self.processes)
        for process in processes:
            self.kill(process)

    def run(self, name, catalog, local_only=False):
        with self.lock:
            if self.cancelled:
                return failed_project(name)
        process = subprocess.Popen(worker_command(name, local_only), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=clean_env(), cwd='/tmp', start_new_session=True)
        with self.lock:
            self.processes.add(process)
            cancelled = self.cancelled
        if cancelled:
            self.kill(process)
        try:
            try:
                output, _ = process.communicate(timeout=PROJECT_BUDGET)
            except subprocess.TimeoutExpired:
                self.kill(process)
                process.communicate()
                return failed_project(name, True)
            if process.returncode or len(output) > 65536:
                return failed_project(name)
            result = json.loads(output)
            if result.get('project') != name:
                return failed_project(name)
            return result
        finally:
            self.kill(process)
            process.wait()
            with self.lock:
                self.processes.discard(process)


def check_projects(names, catalog, local_only=False, _runner=None):
    runner = ProjectRunner()
    previous_signals = {}
    def cancel(signum, _frame):
        runner.stop()
        raise SystemExit(128 + signum)
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_signals[signum] = signal.signal(signum, cancel)
    results = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_runner or runner.run, name, catalog, local_only=local_only): name for name in names}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = failed_project(name)
    finally:
        runner.stop()
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
    return [results[name] for name in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', choices=['all', *PROJECTS], default='all')
    parser.add_argument('--json', action='store_true', help='Structured output')
    parser.add_argument('--local-only', action='store_true', help='Installed metadata only, no network')
    parser.add_argument('--inspect-one', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    catalog = json.loads(Path(__file__).with_name('catalog.json').read_text())
    names = list(PROJECTS) if args.project == 'all' else [args.project]
    if args.inspect_one:
        if args.project == 'all':
            parser.error('--inspect-one requires one fixed project')
        print(json.dumps(check_project(args.project, catalog, local_only=args.local_only)))
        return
    results = check_projects(names, catalog, local_only=args.local_only)
    report = {'schemaVersion': 1, 'checkedAt': datetime.now(timezone.utc).isoformat(),
              'readOnly': True, 'automaticUpdates': False, 'localOnly': args.local_only,
              'projects': results}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('Checked at ' + report['checkedAt'] + ' (read-only; no updates performed)')
        for row in results:
            installed = row['installed']
            print(row['project'] + ': ' + row['comparison']['status'])
            print('  installed: ' + str(installed.get('version') or installed.get('revision') or 'unverified'))
            print('  latest release: ' + str(row['latestRelease'].get('tag') or row['latestRelease']['state']))
            print('  default branch: ' + str(row['defaultBranch'].get('revision') or row['defaultBranch']['state']))
            print('  source: ' + row['repository'])


if __name__ == '__main__':
    main()
