#!/usr/bin/env python3
"""Sandbox helpers for the recorded-shim regression suite.

Every sandbox lives under ``checks/tmp``.  No fixture is imported or executed:
the Docker shim answers pure compile/layout commands with the real tool
functions, and the target/observer are recorded scenarios.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
SHIMS = ROOT / "checks" / "shims"
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
SHIM_RESOLUTIONS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextlib.contextmanager
def sampling_fault_window():
    expected = os.environ.get('HARNESS_SAMPLING_LOCK')
    if expected is None:
        yield
        return
    lock_path = ROOT.parent / '.sampling.lock'
    if expected != str(lock_path):
        raise AssertionError('unexpected-sampling-lock-path')
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        def checked(identity=None):
            fd_stat = os.fstat(fd)
            path_stat = os.lstat(lock_path)
            for item in (fd_stat, path_stat):
                if not stat.S_ISREG(item.st_mode):
                    raise AssertionError('sampling-lock-not-regular')
                if item.st_uid != os.getuid():
                    raise AssertionError('sampling-lock-not-owned')
                if item.st_nlink != 1:
                    raise AssertionError('sampling-lock-link-count')
            actual = (fd_stat.st_dev, fd_stat.st_ino)
            if identity is not None and actual != identity:
                raise AssertionError('sampling-lock-replaced')
            if (path_stat.st_dev, path_stat.st_ino) != actual:
                raise AssertionError('sampling-lock-replaced')
            return actual
        identity = checked()
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AssertionError('sampling-lock-acquire-timeout')
                time.sleep(0.05)
        try:
            checked(identity)
            yield
        finally:
            try:
                checked(identity)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


_SANDBOX_EVIDENCE_TOKENS = (
    'process', 'identity', 'pid', 'cleanup', 'recovery', 'recover',
    'lifecycle', 'attempt', 'plan',
)


def _validate_managed_lock():
    expected = os.environ.get('HARNESS_SAMPLING_LOCK')
    if expected is None:
        return
    lock_path = ROOT.parent / '.sampling.lock'
    if expected != str(lock_path):
        raise AssertionError('unexpected-sampling-lock-path')
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fd_stat = os.fstat(fd)
        path_stat = os.lstat(lock_path)
        for item in (fd_stat, path_stat):
            if not stat.S_ISREG(item.st_mode):
                raise AssertionError('sampling-lock-not-regular')
            if item.st_uid != os.getuid():
                raise AssertionError('sampling-lock-not-owned')
            if item.st_nlink != 1:
                raise AssertionError('sampling-lock-link-count')
        if (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
            raise AssertionError('sampling-lock-replaced')
    finally:
        os.close(fd)


def _strict_sandbox_path(path):
    try:
        base = os.path.abspath(str(ROOT / 'checks' / 'tmp'))
        target = os.path.abspath(str(path))
    except Exception:
        return False
    if target == base:
        return False
    try:
        if os.path.commonpath([base, target]) != base:
            return False
    except Exception:
        return False
    current = base
    for component in [None] + os.path.relpath(target, base).split(os.sep):
        if component is not None:
            current = os.path.join(current, component)
        try:
            item = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
            return False
    return True


def _sandbox_is_disposable(path):
    try:
        top = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(top.st_mode) or not stat.S_ISDIR(top.st_mode):
        return False
    pending = [str(path)]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            return False
        for entry in entries:
            if any(token in entry.name.lower() for token in _SANDBOX_EVIDENCE_TOKENS):
                return False
            try:
                item = entry.stat(follow_symlinks=False)
            except OSError:
                return False
            if stat.S_ISLNK(item.st_mode):
                return False
            if stat.S_ISDIR(item.st_mode):
                pending.append(entry.path)
            elif stat.S_ISREG(item.st_mode):
                try:
                    fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                except OSError:
                    return False
                else:
                    os.close(fd)
            else:
                return False
    return True


class FixtureLinks:
    def __init__(self, root):
        self.root = Path(root)
        self.root_identity = self._identity(self.root)
        if self.root_identity['type'] != stat.S_IFDIR:
            raise ValueError('fixture root is not a directory')
        if self.root_identity['uid'] != os.getuid():
            raise PermissionError('fixture root is not owned')
        self._links = []

    @staticmethod
    def _stat_identity(item):
        return {
            'dev': item.st_dev,
            'ino': item.st_ino,
            'uid': item.st_uid,
            'type': stat.S_IFMT(item.st_mode),
        }

    @classmethod
    def _identity(cls, path, dir_fd=None):
        item = os.lstat(path) if dir_fd is None else os.lstat(path, dir_fd=dir_fd)
        return cls._stat_identity(item)

    def _validate_root(self):
        actual = self._identity(self.root)
        if actual != self.root_identity:
            raise RuntimeError('fixture root identity changed')
        if actual['type'] != stat.S_IFDIR:
            raise RuntimeError('fixture root is not a directory')
        if actual['uid'] != os.getuid():
            raise PermissionError('fixture root ownership changed')

    def _parent_chain(self, parent):
        root = os.path.abspath(str(self.root))
        parent = os.path.abspath(str(parent))
        chain = [{'path': root, 'identity': self.root_identity}]
        relative = os.path.relpath(parent, root)
        if relative != '.':
            current = root
            for component in relative.split(os.sep):
                current = os.path.join(current, component)
                item = self._identity(current)
                if item['type'] != stat.S_IFDIR:
                    raise ValueError('fixture link parent is not a directory')
                if item['uid'] != os.getuid():
                    raise PermissionError('fixture link parent is not owned')
                chain.append({'path': current, 'identity': item})
        return parent, chain

    def _walk_links(self, directory):
        pending = [str(directory)]
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    item = os.lstat(entry.path)
                    if stat.S_ISLNK(item.st_mode):
                        yield os.path.normpath(os.path.abspath(entry.path))
                    elif stat.S_ISDIR(item.st_mode):
                        pending.append(entry.path)

    def track(self, path):
        path = Path(path)
        self._validate_root()
        root = os.path.abspath(str(self.root))
        target = os.path.abspath(str(path))
        try:
            inside = os.path.commonpath([root, target]) == root
        except ValueError:
            inside = False
        if target == root or not inside:
            raise ValueError('fixture link is outside the private root')
        parent, chain = self._parent_chain(path.parent)
        link_identity = self._identity(path)
        if link_identity['type'] != stat.S_IFLNK:
            raise ValueError('fixture link is not a symlink')
        if link_identity['uid'] != os.getuid():
            raise PermissionError('fixture link is not owned')
        self._links.append({
            'path': target,
            'parent': parent,
            'chain': chain,
            'link': link_identity,
            'contents': os.readlink(path),
        })

    def _validate_record(self, record):
        self._validate_root()
        for item in record['chain']:
            actual = self._identity(item['path'])
            if actual != item['identity']:
                raise RuntimeError('fixture parent identity changed')
            if actual['type'] != stat.S_IFDIR:
                raise RuntimeError('fixture parent is not a directory')
            if actual['uid'] != os.getuid():
                raise PermissionError('fixture parent ownership changed')
        actual_link = self._identity(record['path'])
        if actual_link != record['link']:
            raise RuntimeError('fixture link identity changed')
        if actual_link['type'] != stat.S_IFLNK:
            raise RuntimeError('fixture link is no longer a symlink')
        if actual_link['uid'] != os.getuid():
            raise PermissionError('fixture link ownership changed')
        if os.readlink(record['path']) != record['contents']:
            raise RuntimeError('fixture link contents changed')

    def _unlink_record(self, record):
        parent = record['parent']
        parent_identity = record['chain'][-1]['identity']
        flags = (os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                 | getattr(os, 'O_NOFOLLOW', 0))
        descriptor = os.open(parent, flags)
        try:
            actual_parent = self._stat_identity(os.fstat(descriptor))
            if actual_parent != parent_identity:
                raise RuntimeError('fixture link parent identity changed')
            name = os.path.basename(record['path'])
            actual_link = self._identity(name, dir_fd=descriptor)
            if actual_link != record['link']:
                raise RuntimeError('fixture link identity changed')
            if actual_link['type'] != stat.S_IFLNK:
                raise RuntimeError('fixture link is no longer a symlink')
            if actual_link['uid'] != os.getuid():
                raise PermissionError('fixture link ownership changed')
            if os.readlink(name, dir_fd=descriptor) != record['contents']:
                raise RuntimeError('fixture link contents changed')
            os.unlink(name, dir_fd=descriptor)
            try:
                os.lstat(name, dir_fd=descriptor)
            except FileNotFoundError:
                return
            raise RuntimeError('fixture link still present after unlink')
        finally:
            os.close(descriptor)

    def close(self):
        self._validate_root()
        registered = {record['path'] for record in self._links}
        for path in self._walk_links(self.root):
            if path not in registered:
                raise RuntimeError('unregistered fixture symlink retained: ' + path)
        for record in self._links:
            self._validate_record(record)
        for record in self._links:
            self._unlink_record(record)
        self._links = []


def retire_sandbox(path):
    if os.environ.get('HARNESS_SAMPLING_LOCK') is None:
        shutil.rmtree(path, ignore_errors=True)
        return
    _validate_managed_lock()
    target = Path(path)
    if not _strict_sandbox_path(target):
        return False
    if not _sandbox_is_disposable(target):
        return False
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return not os.path.lexists(target)


def verify_shims(env):
    """Require Docker and bpftrace to resolve to this suite's controlled shims.

    A missing shim, a non-executable shim or a path outside ``checks/shims`` is
    a hard failure.  There is deliberately no fallback to a real program.
    """
    resolved = {}
    for name in ("docker", "bpftrace"):
        expected = (SHIMS / name).resolve()
        found = shutil.which(name, path=env.get("PATH", ""))
        if not found:
            raise AssertionError("controlled shim missing from PATH: " + name)
        path = Path(found).resolve()
        if path != expected:
            raise AssertionError("controlled shim mismatch for %s: %s != %s"
                                 % (name, path, expected))
        if not expected.is_file() or not os.access(expected, os.X_OK):
            raise AssertionError("controlled shim is not an executable file: " + name)
        resolved[name] = {
            "name": name,
            "resolvedPath": str(path),
            "expectedPath": str(expected),
            "sha256": sha(path),
            "executable": True,
            "controlledDirectory": str(SHIMS.resolve()),
        }
    SHIM_RESOLUTIONS.update(resolved)
    return resolved


class Sandbox:
    def __init__(self, name, tools_source=None, preflight_id=None, plan_mutator=None):
        self.name = name
        self.path = TMP / (name + "-" + os.urandom(4).hex())
        self.path.mkdir(parents=True)
        shutil.copytree(tools_source or (ROOT / "tools"), self.path / "tools")
        shutil.copytree(ROOT / "fixtures", self.path / "fixtures")
        shutil.copyfile(ROOT / "experiment-plan.json", self.path / "experiment-plan.json")
        if plan_mutator is not None:
            plan = json.loads((self.path / "experiment-plan.json").read_text())
            plan_mutator(plan)
            self.write_json(self.path / "experiment-plan.json", plan)
        (self.path / "codex-review").mkdir()
        (self.path / "state").mkdir()
        self.preflight_id = preflight_id or os.urandom(16).hex()
        self.write_manifest()
        self.write_review()

    def write_json(self, path, value):
        Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="utf-8")

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def write_manifest(self):
        files = {}
        files["experiment-plan.json"] = sha(self.path / "experiment-plan.json")
        for path in sorted((self.path / "fixtures").rglob("*.py")):
            files[str(path.relative_to(self.path))] = sha(path)
        for path in sorted((self.path / "tools").glob("*")):
            if path.is_file():
                files[str(path.relative_to(self.path))] = sha(path)
        manifest = {
            "kind": "stdlib-cli-admission-protocol-manifest",
            "version": 3,
            "phase": "admission-revision",
            "state": "pending-codex-review",
            "files": files,
            "fileCount": len(files),
            "targetExecutions": 0,
            "selfExcluded": True,
        }
        self.write_json(self.path / "protocol-manifest.json", manifest)
        return sha(self.path / "protocol-manifest.json"), manifest

    def write_review(self, blockers=None):
        manifest_sha, _ = self.write_manifest()
        review = {
            "state": "completed",
            "protocolManifestSha256": manifest_sha,
            "blockers": list(blockers or []),
            "reviewer": "recorded-test-review",
        }
        self.write_json(self.path / "codex-review" / "source-review-receipt.json", review)
        return sha(self.path / "codex-review" / "source-review-receipt.json"), review

    def manifest_sha(self):
        return sha(self.path / "protocol-manifest.json")

    def review_sha(self):
        return sha(self.path / "codex-review" / "source-review-receipt.json")

    def write_preflight_license(self, preflight_id=None, review_sha=None, **overrides):
        preflight_id = preflight_id or self.preflight_id
        license_value = {
            "kind": "zero-target-preflight-admission",
            "protocolRevision": 3,
            "state": "approved",
            "allowedCommand": "preflight",
            "maxTargetExecutions": 0,
            "fixturesImported": 0,
            "protocolManifestSha256": self.manifest_sha(),
            "candidateManifestSha256": self.manifest_sha(),
            "sourceReviewReceiptSha256": review_sha or self.review_sha(),
            "preflightId": preflight_id,
            "reviewer": "recorded-test-host",
        }
        parser_path = self.path / "tools" / "buffer_protocol_v2.py"
        template_path = self.path / "tools" / "observer_template_buffer_v2.bt"
        if parser_path.is_file() and template_path.is_file():
            license_value.update({
                "observationProtocol": "buffer-v2",
                "framingPolicy": "end-lf-padding-v1",
                "bufferParserSha256": sha(parser_path),
                "bufferTemplateSha256": sha(template_path),
            })
        license_value.update(overrides)
        self.write_json(self.path / "codex-review" / "preflight-admission.json", license_value)
        return license_value

    def env(self, extra=None):
        env = dict(os.environ)
        env["PATH"] = str(SHIMS) + ":" + env.get("PATH", "")
        env["SCE_ROOT"] = str(self.path)
        env["SCE_SHIM_STATE"] = str(self.path / "state")
        env["SCE_DOCKER_LOG"] = str(self.path / "state" / "docker.log")
        env["SCE_TARGET_EXIT"] = "0"
        env["SCE_OBSERVER_MODE"] = "auto"
        env["SCE_OBSERVER_END"] = "normal"
        env.update(extra or {})
        resolved = verify_shims(env)
        env["SCE_RESOLVED_SHIMS"] = json.dumps(resolved, sort_keys=True)
        return env

    def run(self, args, extra=None, timeout=180):
        return subprocess.run(
            [sys.executable, str(self.path / "tools" / "experiment_runner.py")] + list(args),
            capture_output=True, text=True, env=self.env(extra), timeout=timeout,
        )

    def preflight(self, extra=None, timeout=180, preflight_id=None):
        args = [sys.executable, str(self.path / "tools" / "zero_target_preflight.py"), "preflight"]
        if preflight_id:
            args = [sys.executable, str(self.path / "tools" / "zero_target_preflight.py"),
                    "status", "--preflight-id", preflight_id]
        return subprocess.run(args, capture_output=True, text=True, env=self.env(extra), timeout=timeout)

    def status(self, preflight_id, extra=None):
        return subprocess.run(
            [sys.executable, str(self.path / "tools" / "zero_target_preflight.py"),
             "status", "--preflight-id", preflight_id],
            capture_output=True, text=True, env=self.env(extra), timeout=60,
        )

    def prepare(self, extra=None):
        layout = self.run(["prepare-layout"], extra=extra)
        if layout.returncode != 0:
            raise AssertionError("prepare-layout failed: %s %s" % (layout.returncode, layout.stderr[-400:]))
        bind = self.run(["prepare-bind"], extra=extra)
        if bind.returncode != 0:
            raise AssertionError("prepare-bind failed: %s %s" % (bind.returncode, bind.stderr[-400:]))
        return layout, bind

    def write_formal_admission(self, preflight_sha=None, review_sha=None, allowed=None,
                               preflight_id=None, **overrides):
        preflight_id = preflight_id or self.preflight_id
        preflight_sha = preflight_sha or sha(
            self.path / "preflight" / "evidence" / preflight_id / "preflight-receipt.json"
        )
        review_sha = review_sha or self.review_sha()
        allowed = list(allowed or range(1, 17))
        admission = {
            "kind": "experiment-admission",
            "protocolRevision": 3,
            "state": "approved",
            "reviewer": "recorded-test-host",
            "reviewReceiptSha256": review_sha,
            "protocolManifestSha256": self.manifest_sha(),
            "preflightReceiptSha256": preflight_sha,
            "sourceReviewReceiptSha256": review_sha,
            "preflightId": preflight_id,
            "preflightReceiptPath": "preflight/evidence/%s/preflight-receipt.json" % preflight_id,
            "allowedAttempts": allowed,
            "maxTargetExecutions": len(allowed),
            "allowedPrepareSteps": ["layout-v1", "bind-all", "compile-per-attempt"],
        }
        admission.update(overrides)
        self.write_json(self.path / "codex-review" / "experiment-admission.json", admission)
        return admission

    def run_attempt(self, number, exit_code=0, mode="auto", end="normal", extra=None):
        env = {
            "SCE_TARGET_EXIT": str(exit_code),
            "SCE_OBSERVER_MODE": mode,
            "SCE_OBSERVER_END": end,
        }
        env.update(extra or {})
        return self.run(["run", "--attempt", str(number)], extra=env)

    def attempt(self, number):
        return self.read_json(self.path / "state" / ("attempt-%04d.json" % number))

    def verdict(self, number):
        path = self.path / "runs" / ("%04d" % number) / "verification.json"
        return self.read_json(path) if path.is_file() else None

    def observation(self, number):
        path = self.path / "runs" / ("%04d" % number) / "observation.json"
        return self.read_json(path) if path.is_file() else None

    def docker_lines(self):
        path = self.path / "state" / "docker.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def preflight_receipt_path(self, preflight_id=None):
        preflight_id = preflight_id or self.preflight_id
        return self.path / "preflight" / "evidence" / preflight_id / "preflight-receipt.json"

    def preflight_evidence(self, preflight_id=None):
        preflight_id = preflight_id or self.preflight_id
        return self.path / "preflight" / "evidence" / preflight_id

    def fully_ready(self, allowed_attempt=1):
        self.write_preflight_license()
        result = self.preflight()
        if result.returncode != 0:
            raise AssertionError("preflight failed: %s %s" % (result.returncode, result.stderr[-600:]))
        self.write_formal_admission(allowed=[allowed_attempt])
        self.prepare()
        return result
