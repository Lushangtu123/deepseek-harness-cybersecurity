#!/usr/bin/env python3
"""Bounded END-LF framing policy tests (offline and synthetic only).

The historical ``proof/observer.raw`` is parsed as immutable diagnostic data:
its 306 original bytes, including the three extra LF bytes after END, are used
without trimming or rewriting.  No result here is a new post-freeze execution
receipt and no target, container, selfcheck or real bpftrace is run.

The suite covers:

* the requested ``end-lf-padding-v1`` allowance (0, 1, 3, 8 extra LF; 9 invalid);
* blanks in every other location and non-LF trailers;
* strict payload/count/index/identity/mixed-protocol rejections;
* explicit collector policy admission and unchanged legacy/v1 behaviour;
* license/claim/completed/capture/receipt policy binding before resources;
* producer and full-verifier reparsing of the actual raw bytes instead of
  trusting stored policy/trailer metadata;
* separate synthetic mutations of policy, padding count, raw digest, observer
  bytes plus stored hash, and frozen-template binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BASELINE = ROOT / "baseline"
PROOF = ROOT / "proof" / "observer.raw"
RUN_ID = "preflight"
TAG = "0123456789abcdef"
CALLER = "/review/preflight/preflight_selfcheck.py"
CALL_OFFSET = 14
PID = 4242
UID = 65534
POLICY = "end-lf-padding-v1"
PROOF_TAG = "66e7bbb39ef1553b"
PROOF_PID = 1688865
PROOF_RAW_SHA = "5e61c6b689cf4e31905fb6e2863648a0c1d0376446d8dc237189b9cc8627806b"
PROOF_STRUCTURE_SHA = "daa75692969ee231c422d100d6e347d01b8543ab75fff5d08322ff1d8943fc5c"
PROOF_CODE_SHA = "59fbf27117957f3b933508fb2670f31f9c6b2bc56f93e1b71367abb7e31df898"
PROOF_CALLER_SHA = "24484cc8305b002a8fcb007e769b717cb6cd622b07e46991611b208b87ed3b65"

sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(TOOLS))

import buffer_protocol  # noqa: E402
import buffer_protocol_v2  # noqa: E402
import observation_pure  # noqa: E402
import preflight_verify  # noqa: E402
import regression_lib  # noqa: E402
import run_buffer_preflight_checks as focused  # noqa: E402

TESTS = []


def test(name):
    def register(function):
        TESTS.append((name, function))
        return function

    return register


def assert_true(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def assert_equal(left, right, message="values differ"):
    if left != right:
        raise AssertionError("%s: %r != %r" % (message, left, right))


def sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def stream(extra_lf=0, **kwargs):
    return focused.make_stream(protocol="buffer-v2", **kwargs) + "\n" * extra_lf


def parse(raw, *, policy=POLICY, tag=TAG, raw_truncated=False, require_events=1):
    if isinstance(raw, str):
        raw = raw.encode("ascii")
    kwargs = {
        "max_events": 4,
        "raw_truncated": raw_truncated,
        "require_events": require_events,
    }
    if policy is not None:
        kwargs["framing_policy"] = policy
    return buffer_protocol_v2.parse_receipt(
        raw, RUN_ID, tag, CALLER, CALL_OFFSET, PID, UID, **kwargs
    )


def error_text(receipt):
    return " ".join(receipt.get("errors") or [])


def source_snapshot():
    files = {}
    for directory, pattern in (("tools", "*"), ("checks", "*.py"),
                               ("checks/shims", "*"), ("docs", "*.md"),
                               ("fixtures", "**/*.py")):
        base = ROOT / directory
        for path in sorted(base.glob(pattern)):
            if path.is_file() and "__pycache__" not in path.parts:
                files[str(path.relative_to(ROOT))] = sha_file(path)
    for relative in ("BUFFER-PREFLIGHT-CONTRACT.md", "BUFFER-V2-CONTRACT.md",
                     "DIAGNOSTICS-CONTRACT.md", "REPAIR-CONTRACT.md",
                     "END-LF-CONTRACT.md", "experiment-plan.json"):
        path = ROOT / relative
        if path.is_file():
            files[relative] = sha_file(path)
    return files


# ---------------------------------------------------------------------------
# Historical diagnostic proof (not a new execution receipt)
# ---------------------------------------------------------------------------
@test("proof-306-original-bytes-complete-with-three-trailing-blank-lines")
def proof_original_bytes_complete():
    raw = PROOF.read_bytes()
    assert_equal(len(raw), 306, "original proof bytes")
    assert_equal(sha_bytes(raw), PROOF_RAW_SHA, "original proof digest")
    assert_equal(raw[-20:], b"ef1553b events=1\n\n\n\n", "original proof tail")
    receipt = parse(raw, tag=PROOF_TAG)
    assert_equal(receipt.get("state"), "complete", error_text(receipt))
    assert_equal(receipt.get("errors"), [], "errors")
    assert_equal(receipt.get("framingPolicy"), POLICY)
    assert_equal(receipt.get("trailingBlankLines"), 3)
    assert_equal(receipt.get("rawBytes"), 306)
    assert_equal(receipt.get("rawSha256"), PROOF_RAW_SHA)
    assert_equal(receipt.get("targetExecuted"), False)
    assert_equal(receipt.get("targetSelfReportUsed"), False)
    assert_equal(receipt.get("protocol"), "buffer-v2")
    assert_equal(receipt.get("marker"), "BUFFER-PROTOCOL buffer-v2")
    assert_equal(receipt.get("begin"), "run=preflight tag=" + PROOF_TAG)
    assert_equal(receipt.get("end"), "run=preflight tag=" + PROOF_TAG + " events=1")
    assert_equal(len(receipt.get("events") or []), 1)
    event = receipt["events"][0]
    assert_equal(event.get("callerOffset"), 14)
    assert_equal(event.get("dynamicStructureSha256"), PROOF_STRUCTURE_SHA)
    assert_equal(event.get("dynamicCodeSha256"), PROOF_CODE_SHA)
    assert_equal(event.get("callerSha256"), PROOF_CALLER_SHA)
    consts = (event.get("dynamicStructure") or {}).get("consts") or []
    assert_true({"t": "int", "v": 0} in consts, "integer zero lost")
    # The parser is pure and the historical stream remains byte-identical.
    assert_equal(sha_file(PROOF), PROOF_RAW_SHA)
    return {"state": receipt["state"], "rawBytes": receipt["rawBytes"],
            "rawSha256": receipt["rawSha256"],
            "trailingBlankLines": receipt["trailingBlankLines"],
            "dynamicStructureSha256": event["dynamicStructureSha256"],
            "dynamicCodeSha256": event["dynamicCodeSha256"],
            "callerSha256": event["callerSha256"]}


@test("golden-extra-lf-0-1-3-8-accepted-and-9-overflow")
def golden_extra_lf():
    observed = {}
    base_event = None
    for extra in (0, 1, 3, 8):
        raw = stream(extra).encode("ascii")
        receipt = parse(raw)
        assert_equal(receipt.get("state"), "complete", "%d: %s" % (extra, error_text(receipt)))
        assert_equal(receipt.get("framingPolicy"), POLICY)
        assert_equal(receipt.get("trailingBlankLines"), extra)
        assert_equal(receipt.get("rawBytes"), len(raw))
        assert_equal(receipt.get("rawSha256"), sha_bytes(raw))
        assert_equal(receipt.get("targetExecuted"), False)
        event = receipt["events"][0]
        if base_event is None:
            base_event = event
        else:
            assert_equal(event, base_event, "semantic event changed by LF padding")
        observed[str(extra)] = {
            "state": receipt["state"], "trailingBlankLines": extra,
            "rawBytes": len(raw), "rawSha256": sha_bytes(raw),
            "dynamicStructureSha256": event["dynamicStructureSha256"],
        }
    overflow_raw = stream(9).encode("ascii")
    overflow = parse(overflow_raw)
    assert_equal(overflow.get("state"), "invalid")
    assert_equal(overflow.get("errors"), ["trailing-lf-overflow"],
                 error_text(overflow))
    assert_equal(overflow.get("rawSha256"), sha_bytes(overflow_raw))
    assert_equal(overflow.get("trailingBlankLines"), None)
    return observed


@test("end-normal-lf-is-required-and-separate-from-extra-padding")
def end_normal_lf_required():
    normal = stream(0).encode("ascii")
    assert_true(normal.endswith(b"events=1\n"))
    assert_equal(parse(normal).get("trailingBlankLines"), 0)
    unterminated = normal[:-1]
    receipt = parse(unterminated)
    assert_equal(receipt.get("state"), "invalid")
    assert_true("end-unterminated" in error_text(receipt), error_text(receipt))
    no_end = b"\n".join(normal.splitlines()[:-1]) + b"\n"
    missing = parse(no_end)
    assert_equal(missing.get("state"), "invalid")
    assert_equal(missing.get("errors"), ["end-missing"], error_text(missing))
    truncated = parse(normal, raw_truncated=True)
    assert_equal(truncated.get("errors"), ["raw-truncated"])
    return {"unterminated": receipt.get("errors"), "missing": missing.get("errors")}


@test("blank-lines-before-begin-marker-event-and-end-rejected")
def blanks_other_locations_rejected():
    base = stream(0)
    lines = base.splitlines()
    end_index = next(index for index, line in enumerate(lines) if line.startswith("END "))
    cases = {
        "before-begin": "\n" + base,
        "after-begin": "\n".join([lines[0], ""] + lines[1:]) + "\n",
        "before-marker": "\n".join([lines[0], ""] + lines[1:]) + "\n",
        "before-event": "\n".join([lines[0], lines[1], ""] + lines[2:]) + "\n",
        "internal-record": "\n".join(lines[:5] + [""] + lines[5:]) + "\n",
        "before-end": "\n".join(lines[:end_index] + [""] + lines[end_index:]) + "\n",
    }
    observed = {}
    for name, text in cases.items():
        receipt = parse(text)
        assert_equal(receipt.get("state"), "invalid", name)
        assert_equal(receipt.get("errors"), ["ParseError:blank-line"],
                     name + ": " + error_text(receipt))
        observed[name] = receipt.get("rawSha256")
    return observed


@test("tail-whitespace-cr-record-and-duplicate-end-rejected")
def tail_whitespace_and_records_rejected():
    base = stream(0)
    end_line = "END run=%s tag=%s events=1" % (RUN_ID, TAG)
    cases = {
        "space": (base + " \n", "ParseError:line-spacing"),
        "tab": (base + "\t\n", "ParseError:line-control"),
        "cr": (base + "\r\n", "ParseError:line-control"),
        "nonempty": (base + "x\n", "trailing-after-end"),
        "record-after-end": (base + "QUALB 1 61\n", "trailing-after-end"),
        "duplicate-end": (base + end_line + "\n", "end-duplicate"),
    }
    observed = {}
    for name, (text, expected) in cases.items():
        receipt = parse(text)
        assert_equal(receipt.get("state"), "invalid", name)
        assert_equal(receipt.get("errors"), [expected], name + ": " + error_text(receipt))
        observed[name] = {"errors": receipt.get("errors"),
                          "rawSha256": receipt.get("rawSha256")}
    return observed


@test("strict-payload-mixed-count-identity-and-bad-policy-still-rejected")
def strict_existing_rejections_remain():
    base = stream(0)
    bad_payload = base.replace("QUALB 15 ", "QUALB 15  ").encode("ascii")
    payload = parse(bad_payload)
    assert_equal(payload.get("state"), "invalid")
    assert_true("qualb:spacing" in error_text(payload), error_text(payload))
    uppercase = base.replace("QUALB 15 63", "QUALB 15 6A").encode("ascii")
    assert_true("qualb:hex" in error_text(parse(uppercase)), error_text(parse(uppercase)))
    mixed_marker = base.replace("BUFFER-PROTOCOL buffer-v2", "BUFFER-PROTOCOL buffer-v1")
    assert_equal(parse(mixed_marker).get("errors"), ["marker-invalid"])
    mixed_record = base.replace("QUALB 15", "QUALW 0 15").encode("ascii")
    assert_true("mixed-legacy" in error_text(parse(mixed_record)),
                error_text(parse(mixed_record)))
    count = base.replace("DCONSTN 4\n", "").encode("ascii")
    assert_true("dconst-count-missing" in error_text(parse(count)),
                error_text(parse(count)))
    mismatch = base.replace("events=1", "events=2").encode("ascii")
    assert_equal(parse(mismatch).get("errors"), ["event-count-mismatch"])
    wrong_tag = base.replace("tag=" + TAG, "tag=ffffffffffffffff").encode("ascii")
    assert_equal(parse(wrong_tag).get("errors"), ["begin-mismatch"])
    wrong_policy = parse(base, policy="project-selected-v1")
    assert_equal(wrong_policy.get("state"), "invalid")
    assert_equal(wrong_policy.get("errors"), ["framing-policy"])
    assert_equal(wrong_policy.get("framingPolicy"), POLICY)
    for receipt in (payload, parse(uppercase), parse(mixed_marker), parse(mixed_record),
                    parse(count), parse(mismatch), parse(wrong_tag), wrong_policy):
        assert_true(receipt.get("rawSha256"), "raw digest missing")
        assert_equal(receipt.get("targetExecuted"), False)
    return {"payload": payload.get("errors"), "policy": wrong_policy.get("errors")}


# ---------------------------------------------------------------------------
# Collector explicit policy and legacy/v1 compatibility
# ---------------------------------------------------------------------------
def run_collector(raw_path, out_path, protocol, framing_policy="auto"):
    command = [
        sys.executable, str(TOOLS / "collect_observer.py"),
        "--observation-protocol", protocol,
        "--raw", str(raw_path), "--run-id", RUN_ID, "--tag", TAG,
        "--caller-path", CALLER, "--call-offset", str(CALL_OFFSET),
        "--target-pid", str(PID), "--target-uid", str(UID),
        "--max-events", "4", "--out", str(out_path),
    ]
    if framing_policy == "auto":
        if protocol == "buffer-v2":
            command.extend(["--framing-policy", POLICY])
    elif framing_policy is not None:
        command.extend(["--framing-policy", framing_policy])
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


@test("collector-explicit-policy-missing-unknown-and-legacy-v1-unchanged")
def collector_policy_and_legacy():
    base = ROOT / "checks" / "tmp" / ("end-lf-collector-" + os.urandom(4).hex())
    base.mkdir(parents=True)
    v2_raw = base / "v2.raw"
    v2_raw.write_text(stream(3), encoding="ascii")
    v2_out = base / "v2.json"
    ok = run_collector(v2_raw, v2_out, "buffer-v2")
    assert_equal(ok.returncode, 0, "v2 collector: " + ok.stderr[-300:])
    receipt = json.loads(v2_out.read_text())
    assert_equal(receipt.get("state"), "complete")
    assert_equal(receipt.get("framingPolicy"), POLICY)
    assert_equal(receipt.get("trailingBlankLines"), 3)
    assert_equal(receipt.get("rawBytes"), v2_raw.stat().st_size)
    assert_equal(receipt.get("rawSha256"), sha_file(v2_raw))
    assert_equal(receipt.get("targetExecuted"), False)

    missing_out = base / "missing.json"
    missing = run_collector(v2_raw, missing_out, "buffer-v2", framing_policy=None)
    assert_equal(missing.returncode, 2, "missing policy admitted")
    assert_equal(json.loads(missing.stdout).get("errors"), ["framing-policy-missing"])
    assert_equal(missing_out.exists(), False, "missing policy wrote output")

    unknown_out = base / "unknown.json"
    unknown = run_collector(v2_raw, unknown_out, "buffer-v2",
                            framing_policy="project-selected-v1")
    assert_equal(unknown.returncode, 2, "unknown policy admitted")
    assert_true("invalid choice" in unknown.stderr, unknown.stderr[-300:])
    assert_equal(unknown_out.exists(), False, "unknown policy wrote output")

    legacy_raw = base / "legacy.raw"
    legacy_raw.write_text(focused.make_stream(protocol="legacy"), encoding="ascii")
    legacy_out = base / "legacy.json"
    legacy = run_collector(legacy_raw, legacy_out, "legacy", framing_policy=None)
    assert_equal(legacy.returncode, 0, "legacy collector changed: " + legacy.stderr[-300:])
    legacy_receipt = json.loads(legacy_out.read_text())
    assert_equal(legacy_receipt.get("state"), "complete")
    assert_equal(legacy_receipt.get("targetExecuted"), True)
    assert_equal("framingPolicy" in legacy_receipt, False,
                 "legacy gained v2 framing metadata")
    legacy_flagged = run_collector(legacy_raw, base / "legacy-flag.json",
                                   "legacy", framing_policy=POLICY)
    assert_equal(legacy_flagged.returncode, 2)
    assert_equal(json.loads(legacy_flagged.stdout).get("errors"),
                 ["framing-policy-not-applicable"])

    v1_raw = base / "v1.raw"
    v1_raw.write_text(focused.make_stream(protocol="buffer-v1"), encoding="ascii")
    v1_out = base / "v1.json"
    v1 = run_collector(v1_raw, v1_out, "buffer-v1", framing_policy=None)
    assert_equal(v1.returncode, 0, "v1 collector changed: " + v1.stderr[-300:])
    v1_receipt = json.loads(v1_out.read_text())
    assert_equal(v1_receipt.get("protocol"), "buffer-v1")
    assert_equal("framingPolicy" in v1_receipt, False, "v1 gained v2 framing metadata")
    return {"v2": receipt.get("trailingBlankLines"),
            "missing": json.loads(missing.stdout).get("errors"),
            "legacy": legacy_receipt.get("state"), "v1": v1_receipt.get("state")}


# ---------------------------------------------------------------------------
# Preflight binding and independent reparse
# ---------------------------------------------------------------------------
def new_sandbox(name):
    return regression_lib.Sandbox(name)


def verify_reason(box):
    try:
        preflight_verify.verify_preflight_evidence(
            box.path,
            box.preflight_receipt_path(),
            box.path / "codex-review" / "preflight-admission.json",
            box.path / "codex-review" / "source-review-receipt.json",
            box.path / "protocol-manifest.json",
            box.path / "tools" / "observer-profile.lock.json",
            expected_id=box.preflight_id,
        )
        return None
    except preflight_verify.PreflightError as error:
        return error.reason


def resign(box, mutate=None):
    path = box.preflight_receipt_path()
    receipt = box.read_json(path)
    if mutate is not None:
        mutate(receipt, box.preflight_evidence())
    box.write_json(path, receipt)
    receipt_sha = sha_file(path)
    _claim, completed_path = preflight_verify.claim_paths(box.path, box.preflight_id)
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = receipt_sha
    box.write_json(completed_path, completed)
    return receipt


def accepted_box(name):
    box = new_sandbox(name)
    box.write_preflight_license()
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight: " + result.stderr[-700:])
    return box


@test("preflight-license-claim-completed-capture-receipt-bind-exact-policy")
def preflight_binds_policy():
    box = accepted_box("end-lf-bind")
    receipt = box.read_json(box.preflight_receipt_path())
    assert_equal(receipt.get("state"), "accepted")
    assert_equal(receipt.get("framingPolicy"), POLICY)
    assert_equal(receipt.get("observationProtocol"), "buffer-v2")
    observation = receipt.get("observation") or {}
    assert_equal(observation.get("framingPolicy"), POLICY)
    assert_equal(observation.get("trailingBlankLines"), 0)
    claim_path, completed_path = preflight_verify.claim_paths(box.path, box.preflight_id)
    claim = box.read_json(claim_path)
    completed = box.read_json(completed_path)
    assert_equal(claim.get("framingPolicy"), POLICY)
    assert_equal(completed.get("framingPolicy"), POLICY)
    raw = (box.preflight_evidence() / "observer.raw").read_bytes()
    assert_equal(sha_bytes(raw), receipt["observation"]["rawSha256"])
    recomputed = buffers_parse(raw, receipt["tag"], receipt["targetPid"])
    assert_equal(recomputed.get("state"), "complete")
    assert_equal(recomputed.get("framingPolicy"), POLICY)
    assert_equal(recomputed.get("trailingBlankLines"), 0)
    assert_equal(box.read_json(box.preflight_evidence() / "observation.json"),
                 recomputed, "producer trusted stored observation")
    verified = preflight_verify.verify_preflight_evidence(
        box.path, box.preflight_receipt_path(),
        box.path / "codex-review" / "preflight-admission.json",
        box.path / "codex-review" / "source-review-receipt.json",
        box.path / "protocol-manifest.json",
        box.path / "tools" / "observer-profile.lock.json",
        expected_id=box.preflight_id,
    )
    assert_equal(verified.get("framingPolicy"), POLICY)
    assert_equal(verified.get("trailingBlankLines"), 0)
    status = box.status(box.preflight_id)
    assert_equal(status.returncode, 0, status.stdout + status.stderr)
    assert_equal(json.loads(status.stdout).get("framingPolicy"), POLICY)
    return {"receipt": receipt["framingPolicy"], "claim": claim["framingPolicy"],
            "completed": completed["framingPolicy"]}


def buffers_parse(raw, tag, target_pid):
    return buffer_protocol_v2.parse_receipt(
        raw, RUN_ID, tag, CALLER, CALL_OFFSET, target_pid, UID,
        max_events=4, raw_truncated=False, require_events=1,
        framing_policy=POLICY,
    )


@test("producer-and-verifier-reparse-raw-and-compare-policy-and-trailer")
def reparse_raw_not_stored_fields():
    box = accepted_box("end-lf-reparse")
    evidence = box.preflight_evidence()
    raw_path = evidence / "observer.raw"
    observation_path = evidence / "observation.json"
    original_raw = raw_path.read_bytes()
    original_observation = observation_path.read_bytes()
    original_receipt = box.read_json(box.preflight_receipt_path())

    # Stored trailer metadata alone is not trusted: it is recomputed from raw.
    stored = box.read_json(observation_path)
    stored["trailingBlankLines"] = 3
    box.write_json(observation_path, stored)
    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "observationSha256", sha_file(observation_path)))
    assert_equal(verify_reason(box), "observation-mismatch",
                 "stored padding metadata trusted")

    observation_path.write_bytes(original_observation)
    box.write_json(box.preflight_receipt_path(), original_receipt)
    completed_path = preflight_verify.claim_paths(box.path, box.preflight_id)[1]
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = sha_file(box.preflight_receipt_path())
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), None, "restore failed")

    # Change the actual raw bytes (bounded padding) and every stored digest:
    # the verifier must accept the recomputed raw, not an old cached field.
    padded = original_raw + b"\n\n\n"
    raw_path.write_bytes(padded)
    observation = box.read_json(observation_path)
    observation["rawSha256"] = sha_bytes(padded)
    observation["rawBytes"] = len(padded)
    observation["trailingBlankLines"] = 3
    box.write_json(observation_path, observation)
    receipt = box.read_json(box.preflight_receipt_path())
    capture = receipt["observation"]
    capture["rawSha256"] = sha_bytes(padded)
    capture["rawBytes"] = len(padded)
    capture["trailingBlankLines"] = 3
    capture["observationSha256"] = sha_file(observation_path)
    box.write_json(box.preflight_receipt_path(), receipt)
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = sha_file(box.preflight_receipt_path())
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), None, "padded actual raw not reparsed")
    verified = preflight_verify.verify_preflight_evidence(
        box.path, box.preflight_receipt_path(),
        box.path / "codex-review" / "preflight-admission.json",
        box.path / "codex-review" / "source-review-receipt.json",
        box.path / "protocol-manifest.json",
        box.path / "tools" / "observer-profile.lock.json",
        expected_id=box.preflight_id,
    )
    assert_equal(verified.get("trailingBlankLines"), 3)
    assert_equal(verified.get("rawSha256"), sha_bytes(padded))

    # Receipt trailer metadata that disagrees with the actual raw is rejected.
    receipt = box.read_json(box.preflight_receipt_path())
    receipt["observation"]["trailingBlankLines"] = 8
    box.write_json(box.preflight_receipt_path(), receipt)
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = sha_file(box.preflight_receipt_path())
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), "observation-capture-trailing-blank-lines")
    raw_path.write_bytes(original_raw)
    observation_path.write_bytes(original_observation)
    box.write_json(box.preflight_receipt_path(), original_receipt)
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = sha_file(box.preflight_receipt_path())
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), None, "final restore failed")
    return {"paddedTrailingBlankLines": 3, "disagreeReason":
            "observation-capture-trailing-blank-lines"}


@test("synthetic-receipt-policy-padding-digest-observer-freeze-mutations-rejected")
def synthetic_mutations_rejected():
    box = accepted_box("end-lf-mutations")
    policy_reason = None

    resign(box, lambda receipt, ev: receipt.__setitem__("framingPolicy", "project-selected-v1"))
    policy_reason = verify_reason(box)
    assert_equal(policy_reason, "receipt-framing-policy")
    resign(box, lambda receipt, ev: receipt.__setitem__("framingPolicy", POLICY))
    assert_equal(verify_reason(box), None)

    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "framingPolicy", "project-selected-v1"))
    assert_equal(verify_reason(box), "observation-capture-framing-policy")
    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "framingPolicy", POLICY))
    assert_equal(verify_reason(box), None)

    observation_path = box.preflight_evidence() / "observation.json"
    observation = box.read_json(observation_path)
    observation["trailingBlankLines"] = 9
    box.write_json(observation_path, observation)
    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "observationSha256", sha_file(observation_path)))
    assert_equal(verify_reason(box), "observation-mismatch")
    observation["trailingBlankLines"] = 0
    box.write_json(observation_path, observation)
    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "observationSha256", sha_file(observation_path)))
    assert_equal(verify_reason(box), None)

    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "rawSha256", "0" * 64))
    assert_equal(verify_reason(box), "observation-raw")
    resign(box, lambda receipt, ev: receipt["observation"].__setitem__(
        "rawSha256", sha_file(box.preflight_evidence() / "observer.raw")))
    assert_equal(verify_reason(box), None)

    observer_path = box.preflight_evidence() / "observer.bt"
    original_observer = observer_path.read_bytes()

    def mutate_observer(receipt, evidence):
        tamp = evidence / "observer.bt"
        tamp.write_bytes(original_observer + b"\n# tampered observer\n")
        digest = sha_file(tamp)
        receipt["observerTemplateSha256"] = digest
        receipt["observation"]["observerSha256"] = digest

    resign(box, mutate_observer)
    assert_equal(verify_reason(box), "observer-rebuild-mismatch")
    observer_path.write_bytes(original_observer)
    resign(box, lambda receipt, ev: (
        receipt.__setitem__("observerTemplateSha256", sha_file(observer_path)),
        receipt["observation"].__setitem__("observerSha256", sha_file(observer_path)),
    ))
    assert_equal(verify_reason(box), None)

    parser_sha = sha_file(TOOLS / "buffer_protocol_v2.py")
    template_sha = sha_file(TOOLS / "observer_template_buffer_v2.bt")
    resign(box, lambda receipt, ev: receipt.__setitem__(
        "frozenTemplateSha256", "0" * 64))
    assert_equal(verify_reason(box), "receipt-frozen-template-sha")
    resign(box, lambda receipt, ev: (
        receipt.__setitem__("frozenTemplateSha256", template_sha),
        receipt.__setitem__("bufferParserSha256", parser_sha),
    ))
    assert_equal(verify_reason(box), None)

    license_path = box.path / "codex-review" / "preflight-admission.json"
    license_value = box.read_json(license_path)
    license_value["framingPolicy"] = "project-selected-v1"
    box.write_json(license_path, license_value)
    assert_equal(verify_reason(box), "license-framing-policy")
    license_value["framingPolicy"] = POLICY
    box.write_json(license_path, license_value)
    assert_equal(verify_reason(box), None)

    claim_path, completed_path = preflight_verify.claim_paths(box.path, box.preflight_id)
    claim = box.read_json(claim_path)
    claim["framingPolicy"] = "project-selected-v1"
    box.write_json(claim_path, claim)
    assert_equal(verify_reason(box), "claim-framing-policy")
    claim["framingPolicy"] = POLICY
    box.write_json(claim_path, claim)
    assert_equal(verify_reason(box), None)

    completed = box.read_json(completed_path)
    completed["framingPolicy"] = "project-selected-v1"
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), "claim-completed-framing-policy")
    completed["framingPolicy"] = POLICY
    box.write_json(completed_path, completed)
    assert_equal(verify_reason(box), None)
    return {"receiptPolicy": policy_reason,
            "observer": "observer-rebuild-mismatch",
            "licenseClaimCompleted": "separate policy rejects"}


@test("preflight-rejects-missing-or-wrong-policy-before-any-resource")
def policy_before_resources():
    for name, mutate, token in (
        ("missing", lambda value: value.pop("framingPolicy", None),
         "license-framing-policy"),
        ("wrong", lambda value: value.__setitem__("framingPolicy", "legacy"),
         "license-framing-policy"),
    ):
        box = new_sandbox("end-lf-license-" + name)
        box.write_preflight_license()
        path = box.path / "codex-review" / "preflight-admission.json"
        value = box.read_json(path)
        mutate(value)
        box.write_json(path, value)
        result = box.preflight(timeout=60)
        claims = box.path / "preflight" / "claims"
        evidence = box.path / "preflight" / "evidence"
        assert_equal(result.returncode, 78, name + ": " + result.stderr[-300:])
        assert_true(token in result.stderr, name + " reason: " + result.stderr[-300:])
        assert_equal(claims.exists() and any(claims.iterdir()), False,
                     name + " claim created")
        assert_equal(evidence.exists() and any(evidence.iterdir()), False,
                     name + " evidence created")
        assert_equal(len(box.docker_lines()), 0, name + " docker called")
    return {"missing": "license-framing-policy", "wrong": "license-framing-policy"}


@test("legacy-v1-fixed-originals-and-unchanged-surface-bytes")
def fixed_originals_unchanged():
    fixed = (
        "buffer_protocol.py", "observation_pure.py", "structure.py",
        "observer_render.py", "observer_template.bt",
        "observer_template_buffer.bt", "preflight_selfcheck.py",
        "observer-profile.lock.json",
    )
    for name in fixed:
        assert_equal(sha_file(TOOLS / name), sha_file(BASELINE / "tools" / name),
                     "fixed tool changed: " + name)
    # judge.py is a protected module in this baseline: it must remain byte
    # identical to the frozen baseline and be bound by the new manifest.  The
    # only intended changed product tool is experiment_runner.py.
    manifest = json.loads((ROOT / "protocol-manifest.json").read_text(encoding="utf-8"))
    assert_equal(sha_file(TOOLS / "judge.py"),
                 (manifest.get("files") or {}).get("tools/judge.py"),
                 "judge.py not bound by manifest")
    assert_equal(sha_file(TOOLS / "judge.py"),
                 sha_file(BASELINE / "tools" / "judge.py"),
                 "judge.py unexpectedly changed")
    assert_true(sha_file(TOOLS / "experiment_runner.py")
                != sha_file(BASELINE / "tools" / "experiment_runner.py"),
                "intended runner change missing")
    assert_equal(sha_file(ROOT / "experiment-plan.json"),
                 sha_file(BASELINE / "experiment-plan.json"), "plan changed")
    for relative in ("fixtures/echo/sce_echo_sink.py",
                     "fixtures/safe-quoting/sce_quoted_sink.py",
                     "fixtures/structure-controlled/sce_raw_sink.py",
                     "fixtures/wrong-function/sce_two_sites.py"):
        assert_equal(sha_file(ROOT / relative), sha_file(BASELINE / relative),
                     "fixture changed: " + relative)
    # v1 parser still rejects spaced v2 wire and accepts its own contiguous bytes.
    v1_text = focused.make_stream(protocol="buffer-v1")
    assert_equal(buffer_protocol.parse_receipt(
        v1_text.encode("ascii"), RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, require_events=1).get("state"), "complete")
    assert_equal(buffer_protocol.parse_receipt(
        focused.make_stream(protocol="buffer-v2").encode("ascii"), RUN_ID, TAG,
        CALLER, CALL_OFFSET, PID, UID, max_events=4, require_events=1
    ).get("state"), "invalid")
    return {"fixedTools": len(fixed)}


@test("end-lf-contract-and-manifest-bind-changed-trusted-code")
def contract_and_manifest_closure():
    contract = ROOT / "END-LF-CONTRACT.md"
    assert_true(contract.is_file(), "END-LF-CONTRACT.md missing")
    manifest_path = ROOT / "protocol-manifest.json"
    assert_true(manifest_path.is_file(), "protocol-manifest.json missing")
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get("files") or {}
    assert_equal(manifest.get("observationProtocol"), "buffer-v2")
    assert_equal(manifest.get("framingPolicy"), POLICY)
    assert_equal(manifest.get("state"), "pending-codex-review")
    assert_equal(manifest.get("selfcheckExecutions"), 0)
    assert_equal(manifest.get("formalTargets"), "0/16")
    assert_equal(manifest.get("r3"), "blocked")
    for relative in ("tools/buffer_protocol_v2.py", "tools/collect_observer.py",
                     "tools/preflight_verify.py", "tools/zero_target_preflight.py",
                     "END-LF-CONTRACT.md", "checks/run_end_lf_checks.py",
                     "checks/run_buffer_preflight_checks.py",
                     "checks/run_buffer_v2_red.py", "checks/regression_lib.py"):
        assert_true(relative in files, "manifest missing " + relative)
    mismatched = [relative for relative, digest in files.items()
                  if not (ROOT / relative).is_file()
                  or sha_file(ROOT / relative) != digest]
    assert_equal(mismatched, [], "manifest mismatches")
    assert_equal(manifest.get("fileCount"), len(files))
    assert_true("baseline/" not in " ".join(files), "baseline included")
    assert_true("proof/" not in " ".join(files), "proof included")
    text = contract.read_text(encoding="utf-8")
    assert_true(PROOF_RAW_SHA in text, "contract does not bind historical raw hash")
    assert_true(POLICY in text, "contract does not name framing policy")
    assert_true("306" in text, "contract does not state 306 bytes")
    return {"manifestSha256": sha_file(manifest_path),
            "fileCount": manifest.get("fileCount")}


# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "checks" / "end-lf-results.json"))
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    selected = [(name, fn) for name, fn in TESTS if not args.only or args.only in name]
    if not selected:
        raise SystemExit("no tests selected")
    before = source_snapshot()
    entries = []
    failures = []
    for name, function in selected:
        try:
            detail = function()
            entries.append({"test": name, "passed": True, "detail": detail})
            print("PASS " + name)
        except BaseException as error:  # noqa: BLE001
            entry = {"test": name, "passed": False,
                     "error": type(error).__name__ + ":" + str(error),
                     "trace": traceback.format_exc()[-5000:]}
            entries.append(entry)
            failures.append(name)
            print("FAIL " + name)
            print(entry["trace"])
    after = source_snapshot()
    payload = {
        "kind": "end-lf-padding-v1-focused-results",
        "version": 1,
        "protocolRevision": 3,
        "observationProtocol": "buffer-v2",
        "framingPolicy": POLICY,
        "simulated": True,
        "targetExecutions": 0,
        "fixturesImported": 0,
        "realContainers": 0,
        "realBpftrace": 0,
        "preflightExecuted": False,
        "selfcheckExecuted": False,
        "admissionIssued": False,
        "formalTargets": "0/16",
        "r3": "blocked",
        "proofRawSha256": PROOF_RAW_SHA,
        "proofRawBytes": 306,
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceUnchanged": before == after,
        "results": entries,
        "passed": sum(1 for item in entries if item["passed"]),
        "failed": failures,
        "total": len(entries),
        "note": "Synthetic/recorded-shim tests only; historical proof is diagnostic, not a new receipt.",
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                      encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": failures,
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
