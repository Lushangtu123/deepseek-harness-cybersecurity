#!/usr/bin/env python3
"""Helpers for the SIMULATED formal runner/judge admission checks.

Every Docker/bpftrace resolution is checked against ``checks/shims`` before a
sandbox runs, and in-process cases monkeypatch resource functions.  No real
container, observer, target, preflight or selfcheck is ever started.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CHECKS = Path(__file__).resolve().parents[1]
ROOT = CHECKS.parent
sys.path.insert(0, str(CHECKS))

import regression_lib  # noqa: E402
from regression_lib import Sandbox, sha  # noqa: E402


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def preflight_ready(box, preflight_id=None):
    box.write_preflight_license(preflight_id=preflight_id)
    result = box.preflight()
    if result.returncode != 0:
        raise AssertionError("preflight failed: %s %s" % (result.returncode, result.stderr[-800:]))
    return result


def ready_box(name, allowed=(1,)):
    box = Sandbox(name)
    preflight_ready(box)
    box.write_formal_admission(allowed=list(allowed))
    box.prepare()
    return box


def attempt_path(box, number):
    return box.path / "state" / ("attempt-%04d.json" % number)


def run_dir(box, number):
    return box.path / "runs" / ("%04d" % number)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def plans(box):
    directory = box.path / "prepare" / "plans"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def target_plan(box, number):
    for path in plans(box):
        if path.name.endswith(".identity.json"):
            continue
        value = read_json(path)
        role = value.get("operationRole") or value.get("role") or ""
        if value.get("attempt") == number and role.startswith("run-"):
            return path, value
    return None, None


def judge(box, number, observation=None, attempt=None, raw=None, template=None,
          layout=None, expected=None, binding=None, out=None, extra=None,
          observer=None):
    run = run_dir(box, number)
    out = out or (run / "verification-manual.json")
    command = [
        sys.executable, str(box.path / "tools" / "judge.py"),
        "--binding", str(binding or (box.path / "prepare" / "bind" / "bind.json")),
        "--expected", str(expected or (box.path / "prepare" / ("compile-%04d" % number) / "expected.json")),
        "--observation", str(observation or (run / "observation.json")),
        "--attempt", str(attempt or attempt_path(box, number)),
        "--admission", str(box.path / "codex-review" / "experiment-admission.json"),
        "--manifest", str(box.path / "protocol-manifest.json"),
        "--preflight", str(box.preflight_receipt_path()),
        "--review-receipt", str(box.path / "codex-review" / "source-review-receipt.json"),
        "--observer", str(observer or (run / "observer.bt")),
        "--raw", str(raw or (run / "observer.raw")),
        "--layout", str(layout or (box.path / "prepare" / "layout" / "layout.json")),
        "--template", str(template or (box.path / "tools" / "observer_template_buffer_v2.bt")),
        "--profile", str(box.path / "tools" / "observer-profile.lock.json"),
        "--observation-protocol", "buffer-v2",
        "--framing-policy", "end-lf-padding-v1",
        "--out", str(out),
    ] + list(extra or [])
    result = subprocess.run(command, capture_output=True, text=True,
                            env=box.env(), timeout=90)
    value = read_json(out) if Path(out).is_file() else {}
    return result, value


def resign_observation(box, number, observation_path=None, raw_path=None,
                       attempt_override=None):
    """Re-sign only stored digests; raw/stored-event mismatches must remain."""
    observation_path = Path(observation_path or (run_dir(box, number) / "observation.json"))
    attempt_path_value = Path(attempt_override or attempt_path(box, number))
    observation = read_json(observation_path)
    attempt = read_json(attempt_path_value)
    if raw_path is not None:
        raw = Path(raw_path).read_bytes()
        observation["rawSha256"] = sha_bytes(raw)
        observation["rawBytes"] = len(raw)
        attempt["observationRawSha256"] = sha_bytes(raw)
    write_json(observation_path, observation)
    attempt["observationSha256"] = sha(observation_path)
    write_json(attempt_path_value, attempt)
    return observation, attempt


def docker_lines(box):
    return box.docker_lines()


def docker_count(box, prefix):
    return sum(1 for line in docker_lines(box) if line.startswith(prefix))
