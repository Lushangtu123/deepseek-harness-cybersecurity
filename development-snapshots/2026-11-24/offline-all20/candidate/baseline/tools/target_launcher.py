#!/usr/bin/env python3
"""Target-side launcher for the structural probe experiment (admission revision).

Runs inside the pinned, non-root, network-disabled, read-only container.  It is
*not* the experiment runner and must never be started by preparation tools.

Order of operations (fixes the round-2 blockers):

1. wait for exactly one ``GO`` line on stdin **before touching anything else**;
   the runner sends GO only after the frozen config is mounted read-only and the
   external observer reported BEGIN;
2. clear every inherited environment variable and install the frozen allowlist;
3. read the frozen run config from ``/review/config/run.json`` (read-only mount);
4. replace stdin with ``/dev/null``;
5. set ``sys.argv`` before any project import;
6. install a restrictive meta-path finder *before* the first project import:
   stdlib names resolve only through the fixed stdlib paths, closure modules are
   loaded through a SHA-256-verifying loader, guarded optional imports get a
   deterministic ``ModuleNotFoundError``, everything else is denied;
7. import the frozen ``module``, resolve the frozen dotted ``callable`` and call
   it with no arguments;
8. exit with the callable's real exit status.

The launcher writes no evidence file; its stdout/stderr/exit status are
diagnostic only.  The only execution evidence is the external observer.
"""
import hashlib
import importlib.abc
import importlib.util
import json
import os
import sys

CONFIG_PATH = "/review/config/run.json"
RUNROOT = "/review/runroot"
#: Frozen environment allowlist.  Values are fixed here, never taken from config
#: or from the container image, so an inherited or configured value cannot change
#: what the target sees.
ENV_ALLOWLIST = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "HOSTNAME": "stdlib-cli-experiment",
}


def die(code, message):
    sys.stderr.write("launcher: %s\n" % message[:512])
    raise SystemExit(code)


def wait_for_go():
    """Block until the runner's single GO line; nothing is read before it."""
    line = sys.stdin.buffer.readline(64)
    if line != b"GO\n":
        die(70, "go-handshake")


def clear_environment():
    """Drop every inherited variable, then install exactly the allowlist."""
    inherited = sorted(os.environ)
    extras = [key for key in inherited if key not in ENV_ALLOWLIST]
    os.environ.clear()
    for key, value in ENV_ALLOWLIST.items():
        os.environ[key] = value
    leaked = [key for key in os.environ if key not in ENV_ALLOWLIST]
    if leaked:
        die(71, "environment-leak")
    sys.stderr.write("launcher: env-cleared=%d\n" % len(extras))
    return extras


def detach_stdin():
    try:
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.close(null)
    except OSError:
        die(70, "stdin-detach")


def read_config():
    try:
        with open(CONFIG_PATH, "rb") as handle:
            raw = handle.read(65536)
        config = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError):
        die(71, "config-unreadable")
    if type(config) is not dict or config.get("version") != 1:
        die(71, "config-shape")
    for key in (
        "module",
        "callable",
        "argv",
        "closure",
        "stdlibPaths",
        "allowedEnvKeys",
        "optionalThirdParty",
        "optionalLocalAbsent",
    ):
        if key not in config:
            die(71, "config-key:" + key)
    if type(config["module"]) is not str or not config["module"].replace(".", "").replace("_", "").isalnum():
        die(71, "module-name")
    if type(config["callable"]) is not str or not config["callable"].replace(".", "").replace("_", "").isalnum():
        die(71, "callable-name")
    if type(config["argv"]) is not list or any(type(item) is not str for item in config["argv"]):
        die(71, "argv")
    if type(config["closure"]) is not dict or not config["closure"]:
        die(71, "closure")
    if any(
        type(path) is not str
        or path.startswith("/")
        or ".." in path.split("/")
        or not path.endswith(".py")
        for path in config["closure"]
    ):
        die(71, "closure-path")
    if any(type(value) is not str or len(value) != 64 for value in config["closure"].values()):
        die(71, "closure-digest")
    if type(config["stdlibPaths"]) is not list or not config["stdlibPaths"]:
        die(71, "stdlib-paths")
    if sorted(config["allowedEnvKeys"]) != sorted(ENV_ALLOWLIST):
        die(71, "config-env-allowlist")
    return config


class ClosureLoader(importlib.abc.Loader):
    """Loads exactly the frozen closure bytes after re-verifying SHA-256."""

    def __init__(self, fullname, relative_path, expected_sha):
        self.fullname = fullname
        self.relative_path = relative_path
        self.expected_sha = expected_sha

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        absolute = os.path.join(RUNROOT, *self.relative_path.split("/"))
        try:
            with open(absolute, "rb") as handle:
                data = handle.read(1048577)
        except OSError:
            raise ImportError("closure-unreadable") from None
        if len(data) > 1048576:
            raise ImportError("closure-size")
        if hashlib.sha256(data).hexdigest() != self.expected_sha:
            raise ImportError("closure-digest-mismatch")
        filename = RUNROOT + "/" + self.relative_path
        code = compile(data, filename, "exec", dont_inherit=True, optimize=0)
        exec(code, module.__dict__)  # noqa: S102 - the frozen target itself


class GuardFinder(importlib.abc.MetaPathFinder):
    def __init__(self, config):
        self.closure = dict(config["closure"])
        self.optional_third_party = set(config["optionalThirdParty"])
        self.optional_local_absent = set(config["optionalLocalAbsent"])
        self.denials = []

    def _module_path(self, fullname):
        relative = fullname.replace(".", "/")
        candidate = relative + ".py"
        if candidate in self.closure:
            return candidate
        package = relative + "/__init__.py"
        if package in self.closure:
            return package
        return None

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        # Standard-library names always resolve from the fixed stdlib paths and
        # can never be shadowed by a closure file with the same top-level name.
        if top in sys.stdlib_module_names:
            return None
        relative_path = self._module_path(fullname)
        if relative_path is not None:
            spec = importlib.util.spec_from_loader(
                fullname,
                ClosureLoader(fullname, relative_path, self.closure[relative_path]),
                origin=RUNROOT + "/" + relative_path,
            )
            if spec is None:
                raise ModuleNotFoundError(fullname)
            return spec
        if top in self.optional_local_absent or fullname in self.optional_local_absent:
            self.denials.append({"module": fullname, "reason": "optional-local-absent"})
            raise ModuleNotFoundError(fullname)
        if top in self.optional_third_party or fullname in self.optional_third_party:
            self.denials.append({"module": fullname, "reason": "optional-third-party-absent"})
            raise ModuleNotFoundError(fullname)
        self.denials.append({"module": fullname, "reason": "outside-closure-and-stdlib"})
        raise ModuleNotFoundError(fullname)


def exit_status(result):
    """Translate the entry callable's real return value into a process status."""
    if result is None:
        return 0
    if type(result) is int:
        if 0 <= result <= 255:
            return result
        die(71, "callable-return-range")
    if type(result) is bool:
        return 0
    sys.stderr.write("launcher: callable-return-%s\n" % type(result).__name__)
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv
    # 1. GO first: no config read, no environment decision, no import before it.
    wait_for_go()
    # 2. Clear inherited environment and install the frozen allowlist.
    clear_environment()
    # 3. Only now read the frozen config (the runner has mounted it read-only).
    config = read_config()
    if os.geteuid() == 0:
        die(71, "root-not-allowed")
    # 4. Detach stdin before the first project import.
    detach_stdin()
    sys.argv = [config["module"]] + list(config["argv"])
    sys.path[:] = list(config["stdlibPaths"]) + [RUNROOT]
    finder = GuardFinder(config)
    sys.meta_path.insert(0, finder)
    try:
        module = importlib.import_module(config["module"])
        target = module
        for part in config["callable"].split("."):
            if not part:
                die(72, "callable-part")
            target = getattr(target, part)
        if not callable(target):
            die(72, "callable-not-callable")
        result = target()
    except SystemExit as error:
        code = error.code
        if type(code) is int and 0 <= code <= 255:
            raise
        raise SystemExit(1)
    except BaseException as error:  # noqa: BLE001 - frozen target boundary
        sys.stderr.write("target: %s: %s\n" % (type(error).__name__, str(error)[:512]))
        raise SystemExit(70) from None
    raise SystemExit(exit_status(result))


if __name__ == "__main__":
    raise SystemExit(main())
