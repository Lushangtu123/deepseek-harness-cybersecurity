#!/usr/bin/env python3
"""Focused RED/closure checks for the strict buffer-v2 protocol.

This suite is deliberately small and explicit.  It calls the *actual old*
interfaces (the frozen buffer-v1 parser, the current collector and the current
preflight verifier) so RED is a real behavioural failure, not merely a missing
module.  The same file is retained after implementation as a closure check:
its v1 controls still document the old rejection and its v2 expectations must
then pass.

No Docker, bpftrace, compiler, sudo, fixture, target, selfcheck or admission is
used.  The only subprocess is the candidate collector reading a synthetic raw
file.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "preflight"
TAG = "0123456789abcdef"
CALLER = "/review/preflight/preflight_selfcheck.py"
CALL_OFFSET = 14
PID = 4242
UID = 65534
CODE = bytes([0x9B, 0x00, 0x0C, 0x0D, 0x6A, 0x02, 0x2B, 0x00])


# ---------------------------------------------------------------------------
# Independent formatter control, ported from pinned utils.cpp hex_format_buffer
# ---------------------------------------------------------------------------
def source_formatter(payload, keep_ascii, escape_hex):
    """The pinned upstream loop, expressed directly and independently.

    ``format_string.cpp`` sets ``keep_ascii(false)`` and
    ``escape_hex(false)`` for ``%rh``.  The loop then emits ``%02x`` for every
    byte and appends one ASCII space only when ``i != size - 1``.
    """
    out = []
    for index, byte in enumerate(payload):
        if keep_ascii and 32 <= byte <= 126:
            out.append(chr(byte))
        elif escape_hex:
            out.append("\\x%02x" % byte)
        else:
            out.append("%02x" % byte)
            if index != len(payload) - 1:
                out.append(" ")
    return "".join(out)


def rh(payload):
    return source_formatter(payload, False, False)


def v2_payload(payload):
    return "-" if not payload else rh(payload)


def v1_payload(payload):
    return "-" if not payload else payload.hex()


def spaced_payload(payload):
    return "-" if not payload else " ".join("%02x" % byte for byte in payload)


# ---------------------------------------------------------------------------
# Independent synthetic stream construction
# ---------------------------------------------------------------------------
def make_stream(protocol, *, qual=b"caller.qualname", dconst=b"dynamic-const",
                dname=b"dynamic-name", kconst=b"caller-const",
                kname=b"caller-name", marker_line=None, omit_counts=(),
                legacy_mix=None):
    if protocol not in ("buffer-v1", "buffer-v2"):
        raise ValueError(protocol)
    marker = ("BUFFER-PROTOCOL " + protocol) if marker_line is None else marker_line
    lines = ["BEGIN run=%s tag=%s" % (RUN_ID, TAG), marker,
             "EVENT 11 101 4 22 202 5 %d" % CALL_OFFSET]
    if "DCONSTN" not in omit_counts:
        lines.append("DCONSTN 4")
    if "DNAMEN" not in omit_counts:
        lines.append("DNAMEN 1")
    if "KCONSTN" not in omit_counts:
        lines.append("KCONSTN 4")
    if "KNAMEN" not in omit_counts:
        lines.append("KNAMEN 1")
    lines.extend("DCODE %d %x" % (index, byte) for index, byte in enumerate(CODE))
    payload = v2_payload if protocol == "buffer-v2" else v1_payload
    lines.extend([
        "DCONST 0 n",
        "DCONST 1 i 0 0",
        "DCONST 2 i 0 42",
        "DCONSTB 3 %d %s" % (len(dconst), payload(dconst)),
        "DNAMEB 0 %d %s" % (len(dname), payload(dname)),
        "QUALB %d %s" % (len(qual), payload(qual)),
        "KCONST 0 n",
        "KCONST 1 i 0 0",
        "KCONST 2 i 2 3",
        "KCONSTB 3 %d %s" % (len(kconst), payload(kconst)),
        "KNAMEB 0 %d %s" % (len(kname), payload(kname)),
    ])
    if legacy_mix:
        lines.append(legacy_mix)
    lines.append("END run=%s tag=%s events=1" % (RUN_ID, TAG))
    return "\n".join(lines) + "\n"


def sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def source_snapshot(root=ROOT):
    files = {}
    root = Path(root)
    for directory, pattern in (("tools", "*"), ("checks", "*.py"),
                               ("checks/shims", "*"), ("docs", "*.md"),
                               ("fixtures", "**/*.py")):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            if path.is_file() and "__pycache__" not in path.parts:
                files[str(path.relative_to(root))] = sha_file(path)
    for relative in ("BUFFER-PREFLIGHT-CONTRACT.md", "DIAGNOSTICS-CONTRACT.md",
                     "REPAIR-CONTRACT.md", "experiment-plan.json"):
        path = root / relative
        if path.is_file():
            files[relative] = sha_file(path)
    return files


def load_module(name, tools_dir):
    sys.path.insert(0, str(tools_dir))
    try:
        return importlib.import_module(name)
    finally:
        try:
            sys.path.remove(str(tools_dir))
        except ValueError:
            pass


TESTS = []


def _temporary(prefix):
    base = ROOT / "checks" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


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


# --------------------------------------------------------------------------- formatter
@test("source-formatter-flags-and-golden-separators")
def source_formatter_flags_and_golden_separators():
    assert_equal(rh(b"_run"), "5f 72 75 6e", "_run %rh")
    assert_equal(rh(b"eval"), "65 76 61 6c", "eval %rh")
    assert_equal(rh(b""), "", "empty formatter output")
    assert_equal(rh(b"\x00"), "00", "zero-byte %rh")
    # format_string.cpp: %rh => keep_ascii(false), escape_hex(false).
    assert_equal(source_formatter(b"_run", False, False), "5f 72 75 6e", "%rh flags")
    # %rx => keep_ascii(false), escape_hex(true), no separators.
    assert_equal(source_formatter(b"_run", False, True),
                 "\\x5f\\x72\\x75\\x6e", "%rx flags")
    # %r => keep_ascii(true); printable bytes are not hex-escaped.
    assert_equal(source_formatter(b"_run", True, False), "_run", "%r flags")
    assert_equal(source_formatter(b"A\x00Z", True, False), "A00 Z", "%r nonprintable")
    # Record-level empty uses exactly one dash; it is not formatter output.
    assert_equal(v2_payload(b""), "-", "empty record token")
    assert_equal(v2_payload(b"\x00"), "00", "zero-byte record token")


# --------------------------------------------------------------------------- v1 controls
@test("v1-parser-rejects-spaced-qualb-and-accepts-contiguous")
def v1_parser_rejects_spaced_qualb_and_accepts_contiguous():
    parser = load_module("buffer_protocol", ROOT / "tools")
    spaced = make_stream("buffer-v1")
    spaced = "\n".join(
        "QUALB 4 5f 72 75 6e" if line.startswith("QUALB ") else line
        for line in spaced.splitlines()
    ) + "\n"
    receipt = parser.parse_receipt(
        spaced.encode("ascii"), RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, require_events=1,
    )
    assert_equal(receipt.get("state"), "invalid", "v1 accepted spaced QUALB")
    assert_true(any("qualb-shape" in item for item in receipt.get("errors") or []),
                "v1 spaced reason: " + repr(receipt.get("errors")))
    contiguous = make_stream("buffer-v1")
    compact = parser.parse_receipt(
        contiguous.encode("ascii"), RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, require_events=1,
    )
    assert_equal(compact.get("state"), "complete", "v1 compact control")
    assert_equal(compact.get("protocol"), "buffer-v1")
    # Every spaced multi-byte class is rejected by the old grammar.
    for name, payload in (
        ("DCONSTB", b"dynamic-const"),
        ("DNAMEB", b"dynamic-name"),
        ("QUALB", b"caller.qualname"),
        ("KCONSTB", b"caller-const"),
        ("KNAMEB", b"caller-name"),
    ):
        spaced_line = (name + " " + str(len(payload)) + " " + spaced_payload(payload)
                       if name == "QUALB" else
                       name + " 3 " + str(len(payload)) + " " + spaced_payload(payload)
                       if name in ("DCONSTB", "KCONSTB") else
                       name + " 0 " + str(len(payload)) + " " + spaced_payload(payload))
        text = "\n".join(spaced_line if item.startswith(name + " ") else item
                         for item in contiguous.splitlines()) + "\n"
        result = parser.parse_receipt(
            text.encode("ascii"), RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID,
            max_events=4, require_events=1,
        )
        assert_equal(result.get("state"), "invalid", name + " spaced v1")


# --------------------------------------------------------------------------- collector
@test("collector-supports-explicit-buffer-v2-with-spaced-wire")
def collector_supports_explicit_buffer_v2_with_spaced_wire():
    temporary = _temporary("buffer-v2-red-")
    raw = temporary / "observer.raw"
    out = temporary / "observation.json"
    raw.write_text(make_stream("buffer-v2"), encoding="ascii")
    command = [
        sys.executable, str(ROOT / "tools" / "collect_observer.py"),
        "--observation-protocol", "buffer-v2",
        "--framing-policy", "end-lf-padding-v1",
        "--raw", str(raw), "--run-id", RUN_ID, "--tag", TAG,
        "--caller-path", CALLER, "--call-offset", str(CALL_OFFSET),
        "--target-pid", str(PID), "--target-uid", str(UID),
        "--max-events", "4", "--out", str(out),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert_true(result.returncode == 0,
                "collector did not support buffer-v2: rc=%r stdout=%r stderr=%r"
                % (result.returncode, result.stdout[-400:], result.stderr[-400:]))
    receipt = json.loads(out.read_text())
    assert_equal(receipt.get("state"), "complete")
    assert_equal(receipt.get("protocol"), "buffer-v2")
    assert_equal(receipt.get("targetExecuted"), False)
    raw_text = raw.read_text(encoding="ascii")
    assert_true("QUALB 15 63 61 6c 6c 65 72 2e 71 75 61 6c 6e 61 6d 65" in raw_text,
                "collector sample lacks spaced QUALB")
    shutil.rmtree(temporary, ignore_errors=True)


# --------------------------------------------------------------------------- preflight binding
def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="utf-8")


@test("preflight-verifier-selects-and-binds-actual-v2-material")
def preflight_verifier_selects_and_binds_actual_v2_material():
    verify = load_module("preflight_verify", ROOT / "tools")
    parser_path = ROOT / "tools" / "buffer_protocol_v2.py"
    template_path = ROOT / "tools" / "observer_template_buffer_v2.bt"
    parser_sha = sha_file(parser_path) if parser_path.is_file() else "1" * 64
    template_sha = sha_file(template_path) if template_path.is_file() else "2" * 64
    assert_equal(verify.OBSERVATION_PROTOCOL, "buffer-v2",
                 "preflight still selects v1")
    assert_equal(verify.BUFFER_PARSER_NAME, "buffer_protocol_v2.py")
    assert_equal(verify.BUFFER_TEMPLATE_NAME, "observer_template_buffer_v2.bt")
    temporary = _temporary("buffer-v2-license-")
    manifest_sha = "a" * 64
    review = {"state": "completed", "protocolManifestSha256": manifest_sha,
              "blockers": [], "reviewer": "red-test"}
    review_path = temporary / "review.json"
    write_json(review_path, review)
    review_sha = sha_file(review_path)
    license_value = {
        "kind": "zero-target-preflight-admission",
        "protocolRevision": 3,
        "state": "approved",
        "allowedCommand": "preflight",
        "maxTargetExecutions": 0,
        "fixturesImported": 0,
        "protocolManifestSha256": manifest_sha,
        "candidateManifestSha256": manifest_sha,
        "sourceReviewReceiptSha256": review_sha,
        "preflightId": "a" * 32,
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParserSha256": parser_sha,
        "bufferTemplateSha256": template_sha,
    }
    license_path = temporary / "license.json"
    write_json(license_path, license_value)
    try:
        value, _license_sha, _review, _review_sha, preflight_id = verify.verify_license(
            license_path, review_path, manifest_sha,
            expected_id="a" * 32, parser_sha=parser_sha,
            template_sha=template_sha, require_buffer_protocol=True,
        )
    except verify.PreflightError as error:
        raise AssertionError("old verifier rejected v2 license: " + error.reason) from error
    assert_equal(value.get("observationProtocol"), "buffer-v2")
    assert_equal(preflight_id, "a" * 32)
    shutil.rmtree(temporary, ignore_errors=True)


@test("v2-template-is-byte-derived-and-marker-distinct")
def v2_template_is_byte_derived_and_marker_distinct():
    v1 = ROOT / "tools" / "observer_template_buffer.bt"
    v2 = ROOT / "tools" / "observer_template_buffer_v2.bt"
    assert_true(v2.is_file(), "buffer-v2 template missing")
    old_text = v1.read_text(encoding="utf-8")
    new_text = v2.read_text(encoding="utf-8")
    assert_true("BUFFER-PROTOCOL buffer-v2" in new_text)
    assert_true("BUFFER-PROTOCOL buffer-v1" not in new_text)
    old_body = [line for line in old_text.splitlines()
                if line.strip() and not line.lstrip().startswith("//")]
    new_body = [line for line in new_text.splitlines()
                if line.strip() and not line.lstrip().startswith("//")]
    replaced = [line.replace("BUFFER-PROTOCOL buffer-v1", "BUFFER-PROTOCOL buffer-v2")
                for line in old_body]
    assert_equal(new_body, replaced, "v2 template changed functional body")


@test("v2-parser-accepts-spaced-golden-stream-with-actual-raw-digest")
def v2_parser_accepts_spaced_golden_stream_with_actual_raw_digest():
    module = load_module("buffer_protocol_v2", ROOT / "tools")
    text = make_stream("buffer-v2")
    receipt = module.parse_receipt(
        text.encode("ascii"), RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, require_events=1,
    )
    assert_equal(receipt.get("state"), "complete", receipt.get("errors"))
    assert_equal(receipt.get("protocol"), "buffer-v2")
    assert_equal(receipt.get("targetExecuted"), False)
    assert_equal(receipt.get("rawSha256"), sha_bytes(text.encode("ascii")))
    assert_equal(receipt.get("rawBytes"), len(text.encode("ascii")))
    assert_equal(receipt.get("marker"), "BUFFER-PROTOCOL buffer-v2")
    assert_true({"t": "int", "v": 0} in receipt["events"][0]["dynamicStructure"]["consts"])


# --------------------------------------------------------------------------- runner
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(ROOT)
    entries = []
    failures = []
    for name, function in TESTS:
        try:
            function()
            entries.append({"test": name, "passed": True})
            print("PASS " + name)
        except BaseException as error:  # noqa: BLE001 - RED must retain failures
            entry = {
                "test": name,
                "passed": False,
                "error": type(error).__name__ + ":" + str(error),
                "trace": traceback.format_exc()[-4000:],
            }
            entries.append(entry)
            failures.append(name)
            print("FAIL " + name)
            print(entry["trace"])
    after = source_snapshot(ROOT)
    payload = {
        "kind": "buffer-v2-focused-red-or-closure-results",
        "version": 1,
        "protocolRevision": 3,
        "observationProtocol": "buffer-v2",
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
        "command": [sys.executable] + sys.argv,
        "sourceRoot": str(ROOT),
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceUnchanged": before == after,
        "results": entries,
        "passed": sum(1 for item in entries if item["passed"]),
        "failed": failures,
        "total": len(entries),
        "note": "Synthetic/old-interface RED or closure evidence only; no runtime observation.",
    }
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": failures,
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
