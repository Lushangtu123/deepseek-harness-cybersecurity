#!/usr/bin/env python3
"""Sandbox helpers for the recorded-shim regression suite.

Every sandbox lives under ``checks/tmp``.  No fixture is imported or executed:
the Docker shim answers pure compile/layout commands with the real tool
functions, and the target/observer are recorded scenarios.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
SHIMS = ROOT / "checks" / "shims"
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
SHIM_RESOLUTIONS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
