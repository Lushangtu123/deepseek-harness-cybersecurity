#!/usr/bin/env python3
"""Synthetic recovery sandboxes for the final-stage-recheck checks.

All files live under ``checks/tmp``.  Frozen-material verification is replaced
with explicit synthetic controls; container queries, signals and deletions are
explicit no-effect recorders unless a test deliberately uses a local directory
operation.  No real Docker, bpftrace, target, fixture or license is used.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "checks" / "tmp"
TOOLS = ROOT / "tools"


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n",
                    encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SyntheticRecovery:
    """One original-ID claim/evidence tree with stubbed frozen materials."""

    def __init__(self, name, stage_mode="absent"):
        self.sandbox = Path(tempfile.mkdtemp(prefix=name + "-", dir=TMP))
        self.identifier = os.urandom(16).hex()
        self.tag = os.urandom(8).hex()
        self.manifest_sha = "1" * 64
        self.license_sha = "2" * 64
        self.review_sha = "3" * 64
        self.profile_sha = "4" * 64
        self.module = load_module("rev8_preflight_" + os.urandom(4).hex(),
                                  TOOLS / "zero_target_preflight.py")
        self.verify = self.module.preflight_verify
        self._verify_originals = (
            self.verify.verify_manifest,
            self.verify.verify_license,
            self.verify.load_profile,
        )
        self.verify.verify_manifest = lambda *args: ({}, self.manifest_sha)
        self.verify.verify_license = lambda *args, **kwargs: (
            {}, self.license_sha, {}, self.review_sha, self.identifier)
        self.verify.load_profile = lambda *args: ({}, self.profile_sha)
        self._configure_globals()
        self.plan = self.verify.resource_plan(self.identifier, self.tag)
        self.plan_sha = self.verify.resource_plan_digest(self.plan)
        self.evidence = self.verify.evidence_dir(self.sandbox, self.identifier)
        self.stage = self.sandbox / self.plan["stageRelativePath"]
        self.stage_mode = stage_mode
        self._write_claim_and_intent(stage_mode)

    def _configure_globals(self):
        module = self.module
        module.ROOT = self.sandbox
        module.PREFLIGHT_ROOT = self.sandbox / "preflight"
        module.EVIDENCE_ROOT = module.PREFLIGHT_ROOT / "evidence"
        module.CLAIMS_ROOT = module.PREFLIGHT_ROOT / "claims"
        module.RECOVERIES_ROOT = module.PREFLIGHT_ROOT / "recoveries"
        module.LOCK_PATH = module.PREFLIGHT_ROOT / ".preflight.lock"
        module.MANIFEST = self.sandbox / "protocol-manifest.json"
        module.LICENSE = self.sandbox / "license.json"
        module.REVIEW = self.sandbox / "review.json"
        module.TOOLS = TOOLS
        module.PROFILE = TOOLS / "observer-profile.lock.json"

    def _write_claim_and_intent(self, stage_mode):
        self.evidence.mkdir(parents=True)
        claim = self.module.claim_record(
            self.identifier, self.license_sha, self.evidence,
            self.manifest_sha, self.review_sha, self.plan,
        )
        write_json(self.module.CLAIMS_ROOT / (self.identifier + ".json"), claim)
        write_json(self.evidence / "preflight-intent.json", {
            "version": 3,
            "protocolRevision": 3,
            "kind": "zero-target-preflight-intent",
            "preflightId": self.identifier,
            "tag": self.tag,
            "containerName": self.plan["containerName"],
            "imageId": self.plan["imageId"],
            "stageDir": str(self.stage),
            "resourcePlan": self.plan,
            "resourcePlanSha256": self.plan_sha,
        })
        if stage_mode != "present":
            return
        self.stage.mkdir(parents=True)
        (self.stage / "marker").write_text("controlled stage\n", encoding="utf-8")
        identity = self.module.guard.stage_identity(self.stage)
        write_json(self.evidence / "stage-intent.json", {
            "version": 3,
            "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-intent",
            "preflightId": self.identifier,
            "tag": self.tag,
            "stageDir": str(self.stage),
            "toolsDir": str(self.stage / "tools"),
            "plannedTools": list(self.module.FIXED_TOOLS),
            "resourcePlan": self.plan,
            "resourcePlanSha256": self.plan_sha,
        })
        write_json(self.evidence / "stage-started.json", {
            "version": 3,
            "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-started",
            "preflightId": self.identifier,
            "stageDir": str(self.stage),
            "stageIdentity": identity,
        })
        write_json(self.evidence / "stage-created.json", {
            "version": 3,
            "protocolRevision": 3,
            "kind": "zero-target-preflight-stage-created",
            "preflightId": self.identifier,
            "tag": self.tag,
            "stageDir": str(self.stage),
            "stageIdentity": identity,
            "mounts": [],
        })
        self.identity = identity

    def run_recover(self, container_effect=None, final_override=None,
                    fail_recovery_write=False, chmod_during_query=None):
        """Run recover with explicit resource-query/delete recorders."""
        calls = {"containerQuery": 0, "delete": 0, "signal": 0,
                 "stageRelQueries": 0, "stageRelFinalStates": []}
        original_cleanup_container = self.module._cleanup_container
        original_cleanup_stage = self.module.guard.cleanup_stage
        original_safe_lstat = self.module._safe_lstat
        original_write = self.module.guard.write_new_json_document
        original_chmod = None

        user_effect = container_effect

        def effect(context):
            calls["containerQuery"] += 1
            if user_effect is None:
                return {"removed": True, "state": "never-created"}
            value = user_effect(context)
            if chmod_during_query is not None:
                chmod_during_query()
            return value

        def counted_delete(path, identity):
            calls["delete"] += 1
            return original_cleanup_stage(path, identity)

        def safe_lstat(root, relative, kind=None):
            if relative == self.plan["stageRelativePath"]:
                calls["stageRelQueries"] += 1
                if final_override is not None and calls["stageRelQueries"] >= 2:
                    value = dict(final_override)
                    calls["stageRelFinalStates"].append(value.get("state"))
                    return value
            value = original_safe_lstat(root, relative, kind)
            if relative == self.plan["stageRelativePath"]:
                calls["stageRelFinalStates"].append(value.get("state"))
            return value

        def write_new(path, value):
            if fail_recovery_write and Path(path).name.startswith("recovery-"):
                raise OSError("synthetic recovery journal write failure")
            return original_write(path, value)

        self.module._cleanup_container = effect
        self.module.guard.cleanup_stage = counted_delete
        self.module._safe_lstat = safe_lstat
        self.module.guard.write_new_json_document = write_new
        before_files = set(self.evidence.glob("recovery-*.json"))
        fallback_files = set()
        recoveries = self.module.RECOVERIES_ROOT
        if recoveries.is_dir():
            fallback_files = set(recoveries.glob("recovery-*.json"))
        stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(stream):
                code = self.module.recover(self.identifier)
            try:
                evidence_files = set(self.evidence.glob("recovery-*.json"))
            except OSError:
                evidence_files = set()
            files = sorted(evidence_files - before_files)
            if recoveries.is_dir():
                files = sorted(set(files) | (set(recoveries.glob("recovery-*.json"))
                                              - fallback_files))
            lines = [line for line in stream.getvalue().splitlines() if line.strip()]
            summary = json.loads(lines[-1]) if lines else {}
            record = read_json(files[-1]) if files else {}
        finally:
            self.module._cleanup_container = original_cleanup_container
            self.module.guard.cleanup_stage = original_cleanup_stage
            self.module._safe_lstat = original_safe_lstat
            self.module.guard.write_new_json_document = original_write
        present = False
        is_file = False
        is_dir = False
        is_link = False
        try:
            info = os.lstat(self.stage)
            present = True
            is_link = stat.S_ISLNK(info.st_mode)
            is_file = stat.S_ISREG(info.st_mode)
            is_dir = stat.S_ISDIR(info.st_mode)
        except OSError:
            pass
        return {
            "code": code,
            "record": record,
            "summary": summary,
            "calls": calls,
            "files": [str(path) for path in files],
            "stagePath": str(self.stage),
            "stagePresent": is_dir,
            "stageExists": present,
            "stageIsFile": is_file,
            "stageIsLink": is_link,
        }

    def close(self):
        (self.verify.verify_manifest,
         self.verify.verify_license,
         self.verify.load_profile) = self._verify_originals
        shutil.rmtree(self.sandbox, ignore_errors=True)
