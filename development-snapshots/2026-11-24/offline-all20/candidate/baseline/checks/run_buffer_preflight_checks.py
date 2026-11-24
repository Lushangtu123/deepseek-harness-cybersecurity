#!/usr/bin/env python3
"""Focused synthetic tests for buffer-v2 zero-target preflight integration.

These tests are offline and synthetic.  Docker and bpftrace resolve only to the
controlled shims under ``checks/shims``; no container, target, observer,
selfcheck, compiler, bpftrace attachment, sudo, fixture or formal attempt is run.

The suite is deliberately explicit about the frozen boundary:

* the old ``observation_pure.py``/``structure.py``/``observer_template.bt``
  bytes remain unchanged;
* ``buffer_protocol_v2.py`` imports this candidate's frozen siblings;
* collector parsing requires an explicit protocol choice (no sniffing);
* the new zero-target preflight binds ``buffer-v2`` plus actual parser/template
  digests in its license, claim, capture and receipt;
* producer verification and ``preflight_verify`` both parse the original
  ``observer.raw`` with the frozen v2 parser and deterministically rebuild the
  actual ``observer.bt``.

Changed focused tests are documented in ``BUFFER-V2-CONTRACT.md``: the original
nineteen expectations now declare v2, while explicit v1 parser/collector
controls remain and new spacing/hash equivalence cases were added.

A synthetic format test is not observed runtime evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BASELINE = ROOT / "baseline"
RUN_ID = "preflight"
TAG = "0123456789abcdef"
CALLER = "/review/preflight/preflight_selfcheck.py"
CALL_OFFSET = 14
PID = 4242
UID = 65534
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"

sys.path.insert(0, str(ROOT / "checks"))
sys.path.insert(0, str(TOOLS))

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


def require_module(name):
    try:
        return __import__(name)
    except BaseException as error:  # assertion, not collection failure
        raise AssertionError("module unavailable: %s: %s: %s"
                             % (name, type(error).__name__, error)) from error


def buffer_protocol():
    return require_module("buffer_protocol_v2")


def v1_buffer_protocol():
    return require_module("buffer_protocol")


def legacy_parser():
    return require_module("observation_pure")


def preflight_verify():
    return require_module("preflight_verify")


def synthetic_layout():
    offsets = {
        "codeConstsOffset": 32,
        "codeNamesOffset": 40,
        "codeFilenameOffset": 48,
        "codeFlagsOffset": 56,
        "codeFirstlinenoOffset": 60,
        "codeQualnameOffset": 64,
        "codeSizeOffset": 72,
        "codeAdaptiveOffset": 80,
        "tupleSizeOffset": 16,
        "tupleItemsOffset": 24,
        "strLengthOffset": 16,
        "strStateOffset": 24,
        "strDataOffset": 40,
        "typeNameOffset": 8,
        "intTagOffset": 16,
        "intDigitOffset": 24,
    }
    return {
        "offsets": offsets,
        "frameOffsets": {"tstateCframeOffset": 56, "framePrevInstrOffset": 56},
    }


# ---------------------------------------------------------------------------
# Synthetic stream construction
# ---------------------------------------------------------------------------
def _payload_token(payload, protocol):
    if not payload:
        return "-"
    if protocol == "buffer-v2":
        # Independent shim formatter: lower-case byte pairs separated by one
        # ASCII space.  This does not query the tested parser.
        return " ".join("%02x" % byte for byte in payload)
    if protocol == "buffer-v1":
        return payload.hex()
    raise ValueError("unknown-buffer-protocol:" + str(protocol))


def make_stream(
    *,
    protocol,
    run_id=RUN_ID,
    tag=TAG,
    dconst=b"dynamic-const",
    dname=b"dynamic-name",
    qual=b"caller.qualname",
    kconst=b"caller-const",
    kname=b"caller-name",
    marker=True,
    marker_line=None,
    omit_counts=(),
    end_events=None,
    end_line=None,
    begin_line=None,
    extra_lines=(),
    before_marker=(),
    bad_tokens=None,
    legacy_mix=None,
):
    """Return one complete synthetic stream for the requested protocol."""
    code = bytes([0x9B, 0x00, 0x0C, 0x0D, 0x6A, 0x02, 0x2B, 0x00])
    begin = begin_line or ("BEGIN run=%s tag=%s" % (run_id, tag))
    events = 1 if end_events is None else end_events
    end = end_line or ("END run=%s tag=%s events=%d" % (run_id, tag, events))
    if protocol in ("buffer-v1", "buffer-v2"):
        lines = [begin, *before_marker]
        if marker:
            lines.append("BUFFER-PROTOCOL " + protocol if marker_line is None else marker_line)
        lines.extend(extra_lines)
        lines.append("EVENT 11 101 4 22 202 5 %d" % CALL_OFFSET)
        if "DCONSTN" not in omit_counts:
            lines.append("DCONSTN 4")
        if "DNAMEN" not in omit_counts:
            lines.append("DNAMEN 1")
        if "KCONSTN" not in omit_counts:
            lines.append("KCONSTN 4")
        if "KNAMEN" not in omit_counts:
            lines.append("KNAMEN 1")
        lines.extend("DCODE %d %x" % (index, byte) for index, byte in enumerate(code))
        lines.extend([
            "DCONST 0 n",
            "DCONST 1 i 0 0",
            "DCONST 2 i 0 42",
            "DCONSTB 3 %d %s" % (len(dconst), _payload_token(dconst, protocol)),
            "DNAMEB 0 %d %s" % (len(dname), _payload_token(dname, protocol)),
            "QUALB %d %s" % (len(qual), _payload_token(qual, protocol)),
            "KCONST 0 n",
            "KCONST 1 i 0 0",
            "KCONST 2 i 2 3",
            "KCONSTB 3 %d %s" % (len(kconst), _payload_token(kconst, protocol)),
            "KNAMEB 0 %d %s" % (len(kname), _payload_token(kname, protocol)),
        ])
        if legacy_mix:
            lines.append(legacy_mix)
        if bad_tokens:
            name, token = bad_tokens
            lines = [token if line.startswith(name + " ") else line for line in lines]
        lines.append(end)
        return "\n".join(lines) + "\n"

    lines = [begin, "EVENT 11 101 4 22 202 5 %d" % CALL_OFFSET]
    lines.extend("DCODE %d %x" % (index, byte) for index, byte in enumerate(code))
    lines.append("DCONST 0 n")
    lines.append("DCONST 1 i 0 0")
    lines.append("DCONST 2 i 0 42")
    lines.append("DCONST 3 s %d" % len(dconst))
    lines.extend("DCONSTW 3 %d %x" % (index, byte) for index, byte in enumerate(dconst))
    lines.append("DNAME 0 %d" % len(dname))
    lines.extend("DNAMEW 0 %d %x" % (index, byte) for index, byte in enumerate(dname))
    lines.append("QUAL %d" % len(qual))
    lines.extend("QUALW %d %x" % (index, byte) for index, byte in enumerate(qual))
    lines.append("KCONST 0 n")
    lines.append("KCONST 1 i 0 0")
    lines.append("KCONST 2 i 2 3")
    lines.append("KCONST 3 s %d" % len(kconst))
    lines.extend("KCONSTW 3 %d %x" % (index, byte) for index, byte in enumerate(kconst))
    lines.append("KNAME 0 %d" % len(kname))
    lines.extend("KNAMEW 0 %d %x" % (index, byte) for index, byte in enumerate(kname))
    lines.append(end)
    return "\n".join(lines) + "\n"


def parse_buffer(text, *, run_id=RUN_ID, tag=TAG, raw_truncated=False,
                 require_events=1):
    return buffer_protocol().parse_receipt(
        text.encode("ascii"), run_id, tag, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, raw_truncated=raw_truncated, require_events=require_events,
    )


def parse_v1(text, *, run_id=RUN_ID, tag=TAG, raw_truncated=False,
             require_events=1):
    return v1_buffer_protocol().parse_receipt(
        text.encode("ascii"), run_id, tag, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, raw_truncated=raw_truncated, require_events=require_events,
    )


def parse_legacy(text, *, run_id=RUN_ID, tag=TAG, raw_truncated=False,
                 require_events=1):
    return legacy_parser().parse_receipt(
        text.encode("ascii"), run_id, tag, CALLER, CALL_OFFSET, PID, UID,
        max_events=4, raw_truncated=raw_truncated, require_events=require_events,
    )


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------
@test("candidate-sibling-imports-and-frozen-legacy-bytes")
def candidate_sibling_imports_and_frozen_legacy_bytes():
    module = buffer_protocol()
    assert_equal(Path(module._legacy.__file__).resolve(), (TOOLS / "observation_pure.py").resolve())
    assert_equal(Path(module.structure.__file__).resolve(), (TOOLS / "structure.py").resolve())
    for name in ("observation_pure.py", "structure.py", "observer_template.bt"):
        assert_equal(sha_file(TOOLS / name), sha_file(BASELINE / "tools" / name),
                     "frozen tool changed: " + name)
    assert_equal(module.PROTOCOL, "buffer-v2")
    assert_equal(module.MARKER, "BUFFER-PROTOCOL buffer-v2")
    v1 = v1_buffer_protocol()
    assert_equal(v1.PROTOCOL, "buffer-v1")
    assert_equal(v1.MARKER, "BUFFER-PROTOCOL buffer-v1")
    assert_equal(sha_file(TOOLS / "buffer_protocol.py"),
                 sha_file(BASELINE / "tools" / "buffer_protocol.py"))
    assert_equal(sha_file(TOOLS / "observer_template_buffer.bt"),
                 sha_file(BASELINE / "tools" / "observer_template_buffer.bt"))


@test("five-string-classes-lengths-0-1-63-64-accepted")
def five_string_classes_lengths_0_1_63_64_accepted():
    module = buffer_protocol()
    classes = {
        "DCONSTB": "dconst",
        "DNAMEB": "dname",
        "QUALB": "qual",
        "KCONSTB": "kconst",
        "KNAMEB": "kname",
    }
    observed = {}
    for record, field in classes.items():
        for length in (0, 1, 63, 64):
            payload = b"a" * length
            text = make_stream(protocol="buffer-v2", **{field: payload})
            receipt = parse_buffer(text)
            assert_equal(receipt.get("state"), "complete",
                         "%s length %d state" % (record, length))
            assert_equal(receipt.get("protocol"), "buffer-v2")
            assert_equal(receipt.get("targetExecuted"), False)
            observed["%s:%d" % (record, length)] = receipt.get("recordCounts", {}).get(record)
    assert_equal(observed["DCONSTB:64"], 1)
    assert_equal(observed["DNAMEB:64"], 1)
    assert_equal(observed["QUALB:64"], 1)
    assert_equal(observed["KCONSTB:64"], 1)
    assert_equal(observed["KNAMEB:64"], 1)
    del module


@test("five-string-classes-length-65-refused")
def five_string_classes_length_65_refused():
    for field in ("dconst", "dname", "qual", "kconst", "kname"):
        receipt = parse_buffer(make_stream(protocol="buffer-v2", **{field: b"a" * 65}))
        assert_equal(receipt.get("state"), "invalid", field + ":65 state")
        assert_true(receipt.get("errors"), field + ":65 errors missing")


@test("nonascii-payload-invalid-not-exception")
def nonascii_payload_invalid_not_exception():
    for field in ("dconst", "dname", "qual", "kconst", "kname"):
        text = make_stream(protocol="buffer-v2", **{field: b"\x80"})
        try:
            receipt = parse_buffer(text)
        except BaseException as error:  # noqa: BLE001 - must be a receipt
            raise AssertionError("%s non-ascii leaked %s: %s"
                                 % (field, type(error).__name__, error)) from error
        assert_equal(receipt.get("state"), "invalid", field + ":non-ascii state")
        assert_true(any("non-ascii" in item for item in receipt.get("errors") or []),
                    field + ":non-ascii reason")


@test("ascii-specials-and-zero-vs-none-preserved")
def ascii_specials_and_zero_vs_none_preserved():
    payload = b"q\"\\\n\x00z"
    receipt = parse_buffer(make_stream(
        protocol="buffer-v2", dconst=payload, dname=payload, qual=payload,
        kconst=payload, kname=payload,
    ))
    assert_equal(receipt.get("state"), "complete")
    consts = receipt["events"][0]["dynamicStructure"]["consts"]
    assert_true({"t": "int", "v": 0} in consts, "integer zero lost")
    assert_true({"t": "none"} in consts, "None lost")
    assert_true({"t": "str", "v": payload.decode("ascii")} in consts,
                "special ASCII constant not preserved")
    names = receipt["events"][0]["dynamicStructure"]["names"]
    assert_true({"t": "str", "v": payload.decode("ascii")} in names)
    caller = receipt["events"][0]["callerDescriptor"]
    assert_true({"t": "str", "v": payload.decode("ascii")} in caller["consts"])
    assert_equal(caller["qualname"], payload.decode("ascii"))
    assert_true({"t": "str", "v": payload.decode("ascii")} in caller["names"])


@test("count-records-are-mandatory-and-cover-indexes")
def count_records_are_mandatory_and_cover_indexes():
    for missing in ("DCONSTN", "DNAMEN", "KCONSTN", "KNAMEN"):
        receipt = parse_buffer(make_stream(protocol="buffer-v2", omit_counts=(missing,)))
        assert_equal(receipt.get("state"), "invalid", missing + ":missing state")
        assert_true(any("missing" in item for item in receipt.get("errors") or []),
                    missing + ":missing reason: " + repr(receipt.get("errors")))
    for bad_line in ("DCONSTN 3", "DCONSTN 5", "DNAMEN 0", "KCONSTN 3", "KNAMEN 0"):
        text = make_stream(protocol="buffer-v2").replace(
            bad_line.split(" ")[0] + " " + ("4" if bad_line.startswith(("DCONSTN", "KCONSTN")) else "1"),
            bad_line,
        )
        receipt = parse_buffer(text)
        assert_equal(receipt.get("state"), "invalid", bad_line + " state")


@test("malformed-lengths-hex-dash-and-duplicates-refused")
def malformed_lengths_hex_dash_and_duplicates_refused():
    cases = {
        "wrong-length": "DCONSTB 3 4 616263",
        "odd": "DCONSTB 3 3 61626",
        "uppercase": "DCONSTB 3 3 41424A",
        "prefix": "DCONSTB 3 3 0x41",
        "dash-nonzero": "DCONSTB 3 3 -",
        "zero-non-dash": "DCONSTB 3 0 00",
        "too-many-parts": "DCONSTB 3 3 4142 43",
    }
    for label, line in cases.items():
        text = make_stream(protocol="buffer-v2")
        text = "\n".join(line if item.startswith("DCONSTB 3 ") else item
                         for item in text.splitlines()) + "\n"
        receipt = parse_buffer(text)
        assert_equal(receipt.get("state"), "invalid", label + " state")
        assert_true(receipt.get("errors"), label + " errors missing")
    duplicate = make_stream(protocol="buffer-v2")
    inserted = duplicate.splitlines()
    dname_line = next(item for item in inserted if item.startswith("DNAMEB "))
    inserted.insert(inserted.index(dname_line) + 1, "DNAMEB 0 1 61")
    receipt = parse_buffer("\n".join(inserted) + "\n")
    assert_equal(receipt.get("state"), "invalid", "duplicate state")
    assert_true(any("duplicate" in item for item in receipt.get("errors") or []),
                "duplicate reason")


@test("truncation-markers-and-begin-end-attribution")
def truncation_markers_and_begin_end_attribution():
    assert_equal(parse_buffer(make_stream(protocol="buffer-v2"), raw_truncated=True)
                 .get("state"), "invalid")
    for text, token in (
        (make_stream(protocol="buffer-v2", end_line="X"), "end-missing"),
        (make_stream(protocol="buffer-v2", begin_line="BEGIN run=x tag=y"), "begin-mismatch"),
        (make_stream(protocol="buffer-v2", end_line="END run=x tag=y events=1"), "end-mismatch"),
        (make_stream(protocol="buffer-v2", marker=False), "marker-missing"),
        (make_stream(protocol="buffer-v2", marker_line="BUFFER-PROTOCOL buffer-v1"), "marker-invalid"),
        (make_stream(protocol="buffer-v2", before_marker=("X",)), "marker-position"),
    ):
        receipt = parse_buffer(text)
        assert_equal(receipt.get("state"), "invalid")
        assert_true(any(token in item for item in receipt.get("errors") or []),
                    token + " reason: " + repr(receipt.get("errors")))
    duplicate_marker = make_stream(protocol="buffer-v2").replace(
        "BUFFER-PROTOCOL buffer-v2\n",
        "BUFFER-PROTOCOL buffer-v2\nBUFFER-PROTOCOL buffer-v2\n",
    )
    assert_equal(parse_buffer(duplicate_marker).get("state"), "invalid")


@test("legacy-buffer-mix-and-legacy-parser-boundary")
def legacy_buffer_mix_and_legacy_parser_boundary():
    for line in ("DNAMEW 0 0 61", "QUALW 0 61", "DCONSTW 3 0 61",
                 "DNAME 0 1", "KCONST 7 s 1"):
        receipt = parse_buffer(make_stream(protocol="buffer-v2", legacy_mix=line))
        assert_equal(receipt.get("state"), "invalid", line + " mix state")
        assert_true(any("mixed" in item or "legacy" in item for item in receipt.get("errors") or []),
                    line + " mix reason")
    buffer_text = make_stream(protocol="buffer-v2")
    legacy_receipt = parse_legacy(buffer_text)
    assert_equal(legacy_receipt.get("state"), "invalid")
    assert_true(legacy_receipt.get("errors"), "legacy parser accepted buffer marker")


# ---------------------------------------------------------------------------
# Independent formatter and strict spacing controls
# ---------------------------------------------------------------------------
def source_formatter(payload, keep_ascii, escape_hex):
    """Port of pinned ``hex_format_buffer``; independent of either parser."""
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


def record_line(opcode, payload, token, index=None):
    if opcode == "QUALB":
        return "QUALB %d %s" % (len(payload), token)
    return "%s %d %d %s" % (opcode, index, len(payload), token)


RECORD_INDEX = {"DCONSTB": 3, "DNAMEB": 0, "QUALB": None,
                "KCONSTB": 3, "KNAMEB": 0}
RECORD_FIELD = {"DCONSTB": "dconst", "DNAMEB": "dname", "QUALB": "qual",
                "KCONSTB": "kconst", "KNAMEB": "kname"}


@test("source-formatter-flags-golden-pairs-and-record-empty-token")
def source_formatter_flags_golden_pairs_and_record_empty_token():
    assert_equal(source_formatter(b"_run", False, False), "5f 72 75 6e")
    assert_equal(source_formatter(b"eval", False, False), "65 76 61 6c")
    assert_equal(source_formatter(b"", False, False), "")
    assert_equal(source_formatter(b"\x00", False, False), "00")
    assert_equal(source_formatter(b"_run", False, True), "\\x5f\\x72\\x75\\x6e")
    assert_equal(source_formatter(b"_run", True, False), "_run")
    assert_equal(source_formatter(b"A\x00Z", True, False), "A00 Z")
    assert_equal(_payload_token(b"", "buffer-v2"), "-")
    assert_equal(_payload_token(b"\x00", "buffer-v2"), "00")


@test("v2-all-five-records-strict-spacing-and-token-refusal")
def v2_all_five_records_strict_spacing_and_token_refusal():
    valid_payloads = {
        "DCONSTB": b"dynamic-const",
        "DNAMEB": b"dynamic-name",
        "QUALB": b"caller.qualname",
        "KCONSTB": b"caller-const",
        "KNAMEB": b"caller-name",
    }
    malformed = {
        "leading-space": lambda payload: " " + _payload_token(payload, "buffer-v2"),
        "trailing-space": lambda payload: _payload_token(payload, "buffer-v2") + " ",
        "doubled": lambda payload: _payload_token(payload, "buffer-v2").replace(" ", "  ", 1),
        "tab": lambda payload: _payload_token(payload, "buffer-v2").replace(" ", "\t", 1),
        "uppercase": lambda payload: _payload_token(payload, "buffer-v2").upper(),
        "prefix-0x": lambda payload: "0x" + _payload_token(payload, "buffer-v2")[:2],
        "odd-pair": lambda payload: _payload_token(payload, "buffer-v2")[:-1],
        "contiguous": lambda payload: payload.hex(),
        "missing-token": lambda payload: " ".join(
            _payload_token(payload, "buffer-v2").split(" ")[:-1]),
        "extra-token": lambda payload: _payload_token(payload, "buffer-v2") + " 00",
    }
    for opcode, payload in valid_payloads.items():
        field = RECORD_FIELD[opcode]
        index = RECORD_INDEX[opcode]
        valid = record_line(opcode, payload, _payload_token(payload, "buffer-v2"), index)
        for label, build in malformed.items():
            token = build(payload)
            broken = record_line(opcode, payload, token, index)
            text = make_stream(protocol="buffer-v2", **{field: payload})
            lines = [broken if item.startswith(opcode + " ") else item
                     for item in text.splitlines()]
            receipt = parse_buffer("\n".join(lines) + "\n")
            assert_equal(receipt.get("state"), "invalid",
                         "%s %s state" % (opcode, label))
            assert_true(receipt.get("errors"),
                        "%s %s errors" % (opcode, label))
            # The valid line itself remains accepted, so the failure above is
            # caused by the spacing/token change, not by an invalid baseline.
            assert_true(valid.startswith(opcode + " "))


@test("v2-counts-index-gaps-and-map-duplicates-refused")
def v2_counts_index_gaps_and_map_duplicates_refused():
    base = make_stream(protocol="buffer-v2").splitlines()
    # Missing map index while the mandatory count still claims it exists.
    gap = [line for line in base if not line.startswith("DCONSTB 3 ")]
    receipt = parse_buffer("\n".join(gap) + "\n")
    assert_equal(receipt.get("state"), "invalid")
    assert_true(any("index-coverage" in item for item in receipt.get("errors") or []),
                "gap reason: " + repr(receipt.get("errors")))
    # Non-contiguous map index.
    gap = ["DCONSTB 7 13 " + _payload_token(b"dynamic-const", "buffer-v2")
           if line.startswith("DCONSTB 3 ") else line for line in base]
    receipt = parse_buffer("\n".join(gap) + "\n")
    assert_equal(receipt.get("state"), "invalid")
    # Duplicate map index.
    duplicate = list(base)
    line = next(item for item in duplicate if item.startswith("DNAMEB "))
    duplicate.insert(duplicate.index(line) + 1, "DNAMEB 0 1 61")
    receipt = parse_buffer("\n".join(duplicate) + "\n")
    assert_equal(receipt.get("state"), "invalid")
    assert_true(any("duplicate" in item for item in receipt.get("errors") or []))
    # Duplicate mandatory count.
    duplicate_count = list(base)
    duplicate_count.insert(duplicate_count.index("DCONSTN 4") + 1, "DCONSTN 4")
    receipt = parse_buffer("\n".join(duplicate_count) + "\n")
    assert_equal(receipt.get("state"), "invalid")
    assert_true(any("dconstn-duplicate" in item for item in receipt.get("errors") or []),
                "duplicate count reason: " + repr(receipt.get("errors")))


@test("v2-ascii-controls-nul-quote-backslash-and-nonascii-boundary")
def v2_ascii_controls_nul_quote_backslash_and_nonascii_boundary():
    for payload in (bytes(range(0, 64)), bytes(range(64, 128)),
                    b"\x00\x01\t\n\r\"\\\x7fz"):
        receipt = parse_buffer(make_stream(protocol="buffer-v2", qual=payload,
                                           dconst=payload, dname=payload,
                                           kconst=payload, kname=payload))
        assert_equal(receipt.get("state"), "complete",
                     "ASCII payload state: " + repr(payload[:8]))
        assert_equal(receipt["events"][0]["callerDescriptor"]["qualname"],
                     payload.decode("ascii"))
    for payload in (b"\x80", b"a\xffb"):
        receipt = parse_buffer(make_stream(protocol="buffer-v2", qual=payload))
        assert_equal(receipt.get("state"), "invalid")
        assert_true(any("non-ascii" in item for item in receipt.get("errors") or []))


@test("v1-v2-marker-and-single-byte-wire-payload-distinguish-protocols")
def v1_v2_marker_and_single_byte_wire_payload_distinguish_protocols():
    one = {"qual": b"0", "dconst": b"0", "dname": b"0",
           "kconst": b"0", "kname": b"0"}
    v1_text = make_stream(protocol="buffer-v1", **one)
    v2_text = make_stream(protocol="buffer-v2", **one)
    v1_receipt = parse_v1(v1_text)
    v2_receipt = parse_buffer(v2_text)
    assert_equal(v1_receipt.get("state"), "complete", "v1 one-byte")
    assert_equal(v2_receipt.get("state"), "complete", "v2 one-byte")
    assert_true("QUALB 1 30" in v1_text and "QUALB 1 30" in v2_text,
                "single-byte record shape not identical")
    assert_equal(parse_buffer(v1_text).get("state"), "invalid",
                 "v2 admitted v1 marker")
    assert_equal(parse_v1(v2_text).get("state"), "invalid",
                 "v1 admitted v2 marker")
    assert_true(v1_receipt.get("rawSha256") != v2_receipt.get("rawSha256"),
                "protocol raw digests must stay truthful")


@test("legacy-v1-v2-equivalent-capture-identical-canonical-hashes")
def legacy_v1_v2_equivalent_capture_identical_canonical_hashes():
    legacy = parse_legacy(make_stream(protocol="legacy"))
    v1 = parse_v1(make_stream(protocol="buffer-v1"))
    v2 = parse_buffer(make_stream(protocol="buffer-v2"))
    for label, receipt in (("legacy", legacy), ("v1", v1), ("v2", v2)):
        assert_equal(receipt.get("state"), "complete", label + " state")
        assert_equal(len(receipt["events"]), 1, label + " events")
    events = [legacy["events"][0], v1["events"][0], v2["events"][0]]
    assert_equal(events[0], events[1], "legacy/v1 canonical event")
    assert_equal(events[0], events[2], "legacy/v2 canonical event")
    assert_equal(len({event["dynamicStructureSha256"] for event in events}), 1)
    assert_equal(len({event["dynamicCodeSha256"] for event in events}), 1)
    assert_equal(len({event["callerSha256"] for event in events}), 1)
    assert_equal(v1.get("protocol"), "buffer-v1")
    assert_equal(v2.get("protocol"), "buffer-v2")
    assert_true(v1["rawSha256"] != v2["rawSha256"], "raw hashes collapsed")


@test("v2-normalizes-through-frozen-v1-helpers-not-a-translation")
def v2_normalizes_through_frozen_v1_helpers_not_a_translation():
    module = buffer_protocol()
    assert_equal(Path(module._legacy.__file__).resolve(),
                 (TOOLS / "observation_pure.py").resolve())
    assert_equal(Path(module.structure.__file__).resolve(),
                 (TOOLS / "structure.py").resolve())
    v1 = parse_v1(make_stream(protocol="buffer-v1"))
    v2 = parse_buffer(make_stream(protocol="buffer-v2"))
    # The helper-derived canonical objects are identical, but each receipt
    # retains the digest of the actual bytes it parsed.
    assert_equal(v1["events"][0], v2["events"][0])
    assert_equal(v2["rawSha256"], sha_bytes(
        make_stream(protocol="buffer-v2").encode("ascii")))
    assert_true(v1["rawSha256"] != v2["rawSha256"])


@test("v2-unsupported-and-trailing-after-end-rules-preserved")
def v2_unsupported_and_trailing_after_end_rules_preserved():
    text = make_stream(protocol="buffer-v2").replace(
        "END run=%s tag=%s events=1" % (RUN_ID, TAG),
        "UNSUPPORTED dyn-test\nEND run=%s tag=%s events=1" % (RUN_ID, TAG),
    )
    receipt = parse_buffer(text)
    assert_equal(receipt.get("state"), "invalid")
    assert_true(any("unsupported" in item for item in receipt.get("errors") or []))
    stale = make_stream(protocol="buffer-v2") + "x\n"
    receipt = parse_buffer(stale)
    assert_equal(receipt.get("state"), "invalid")
    assert_true(any("trailing-after-end" in item for item in receipt.get("errors") or []))
    duplicate_begin = make_stream(protocol="buffer-v2").replace(
        "BEGIN run=%s tag=%s\n" % (RUN_ID, TAG),
        "BEGIN run=%s tag=%s\nBEGIN run=%s tag=%s\n" % (RUN_ID, TAG, RUN_ID, TAG),
    )
    assert_equal(parse_buffer(duplicate_begin).get("state"), "invalid")


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------
def run_collector(raw_path, out_path, protocol=None, framing_policy="auto"):
    command = [
        sys.executable, str(TOOLS / "collect_observer.py"),
        "--raw", str(raw_path),
        "--run-id", RUN_ID,
        "--tag", TAG,
        "--caller-path", CALLER,
        "--call-offset", str(CALL_OFFSET),
        "--target-pid", str(PID),
        "--target-uid", str(UID),
        "--max-events", "4",
        "--out", str(out_path),
    ]
    if protocol is not None:
        command.extend(["--observation-protocol", protocol])
    if protocol == "buffer-v2" and framing_policy == "auto":
        command.extend(["--framing-policy", "end-lf-padding-v1"])
    elif framing_policy not in (None, "auto"):
        command.extend(["--framing-policy", framing_policy])
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


@test("collector-explicit-protocol-no-sniff-or-fallback")
def collector_explicit_protocol_no_sniff_or_fallback():
    base = ROOT / "checks" / "tmp" / ("collector-" + os.urandom(4).hex())
    base.mkdir(parents=True)
    buffer_raw = base / "buffer.raw"
    buffer_raw.write_text(make_stream(protocol="buffer-v2"), encoding="ascii")
    legacy_raw = base / "legacy.raw"
    legacy_raw.write_text(make_stream(protocol="legacy"), encoding="ascii")

    buffer_out = base / "buffer.json"
    buffer_result = run_collector(buffer_raw, buffer_out, "buffer-v2")
    assert_equal(buffer_result.returncode, 0, "buffer collector rc: " + buffer_result.stderr)
    receipt = json.loads(buffer_out.read_text())
    assert_equal(receipt.get("state"), "complete")
    assert_equal(receipt.get("protocol"), "buffer-v2")
    assert_equal(receipt.get("targetExecuted"), False)
    assert_equal(receipt.get("targetSelfReportUsed"), False)
    assert_equal(receipt.get("marker"), "BUFFER-PROTOCOL buffer-v2")
    assert_true({"t": "int", "v": 0} in receipt["events"][0]["dynamicStructure"]["consts"])
    assert_true({"t": "none"} in receipt["events"][0]["dynamicStructure"]["consts"])

    no_flag = run_collector(buffer_raw, base / "no-flag.json", None)
    assert_equal(no_flag.returncode, 2, "collector must require explicit protocol")
    assert_true("--observation-protocol" in no_flag.stderr)

    legacy_on_buffer = run_collector(buffer_raw, base / "legacy-on-buffer.json", "legacy")
    assert_true(legacy_on_buffer.returncode != 0)
    legacy_receipt = json.loads((base / "legacy-on-buffer.json").read_text())
    assert_equal(legacy_receipt.get("state"), "invalid", "legacy parsed buffer")

    buffer_on_legacy = run_collector(legacy_raw, base / "buffer-on-legacy.json", "buffer-v2")
    assert_true(buffer_on_legacy.returncode != 0)
    wrong_receipt = json.loads((base / "buffer-on-legacy.json").read_text())
    assert_equal(wrong_receipt.get("state"), "invalid", "buffer parsed legacy")

    legacy_out = base / "legacy-ok.json"
    legacy_result = run_collector(legacy_raw, legacy_out, "legacy")
    assert_equal(legacy_result.returncode, 0, "legacy explicit rc")
    legacy_ok = json.loads(legacy_out.read_text())
    assert_equal(legacy_ok.get("state"), "complete")
    assert_equal(legacy_ok.get("targetExecuted"), True)


@test("collector-explicit-v1-diagnostic-and-v2-marker-boundary")
def collector_explicit_v1_diagnostic_and_v2_marker_boundary():
    base = ROOT / "checks" / "tmp" / ("collector-v1-" + os.urandom(4).hex())
    base.mkdir(parents=True)
    v1_raw = base / "v1.raw"
    v1_raw.write_text(make_stream(protocol="buffer-v1"), encoding="ascii")
    v2_raw = base / "v2.raw"
    v2_raw.write_text(make_stream(protocol="buffer-v2"), encoding="ascii")
    v1_out = base / "v1.json"
    result = run_collector(v1_raw, v1_out, "buffer-v1")
    assert_equal(result.returncode, 0, "explicit v1 collector rc: " + result.stderr)
    v1_receipt = json.loads(v1_out.read_text())
    assert_equal(v1_receipt.get("state"), "complete")
    assert_equal(v1_receipt.get("protocol"), "buffer-v1")
    assert_equal(v1_receipt.get("targetExecuted"), False)
    # The retained v1 choice is diagnostic only: it cannot parse v2 wire and
    # the v2 choice cannot parse the v1 marker.
    wrong = run_collector(v2_raw, base / "v1-on-v2.json", "buffer-v1")
    assert_true(wrong.returncode != 0)
    assert_equal(json.loads((base / "v1-on-v2.json").read_text()).get("state"), "invalid")
    wrong = run_collector(v1_raw, base / "v2-on-v1.json", "buffer-v2")
    assert_true(wrong.returncode != 0)
    assert_equal(json.loads((base / "v2-on-v1.json").read_text()).get("state"), "invalid")


# ---------------------------------------------------------------------------
# Template / preflight static integration
# ---------------------------------------------------------------------------
@test("parameterized-buffer-template-preserves-old-bytes-and-fields")
def parameterized_buffer_template_preserves_old_bytes_and_fields():
    import observer_render
    old = (TOOLS / "observer_template.bt").read_bytes()
    assert_equal(sha_bytes(old), sha_file(BASELINE / "tools" / "observer_template.bt"),
                 "old parameterized template bytes changed")
    candidate = TOOLS / "observer_template_buffer_v2.bt"
    assert_true(candidate.is_file(), "new buffer template missing")
    text = candidate.read_text(encoding="utf-8")
    assert_equal(text.count("%rh"), 5, "%rh count")
    assert_equal(text.count("buf(uptr("), 5, "buf(uptr) count")
    for name in ("DCONSTB", "DNAMEB", "QUALB", "KCONSTB", "KNAMEB"):
        assert_true(name in text, name + " missing")
    for name in ("DCONSTN", "DNAMEN", "KCONSTN", "KNAMEN"):
        assert_true(name in text, name + " missing")
    for legacy in ("DCONSTW", "DNAMEW", "QUALW", "KCONSTW", "KNAMEW"):
        assert_true(legacy not in text, legacy + " present")
    assert_true("BUFFER-PROTOCOL buffer-v2" in text)
    assert_true("BUFFER-PROTOCOL buffer-v1" not in text)
    v1_template = TOOLS / "observer_template_buffer.bt"
    assert_equal(sha_file(v1_template), sha_file(BASELINE / "tools" / "observer_template_buffer.bt"))
    assert_true("DCONST %d i 0 0" in text and "KCONST %d i 0 0" in text)
    assert_true("if (pid != __TARGET_PID__)" in text and "if (uid != __TARGET_UID__)" in text)
    assert_true("__TARGET_PID__" in text and "__CALLER_PATH__" in text)
    assert_true("/home/purge" not in text and '"preflight"' not in text)
    assert_equal(text.count("unroll(__MAX_STR__)"), 0, "legacy string unroll remains")
    assert_equal(text.count("unroll(__MAX_DYN_BYTES__)"), 1, "DCODE unroll changed")
    assert_equal(text.count("unroll(8)") + text.count("unroll(__MAX_CONSTS__)"), 2)
    assert_equal(text.count("unroll(16)") + text.count("unroll(__MAX_NAMES__)"), 2)
    old_placeholders = set(re.findall(r"__[A-Z][A-Z0-9_]*__", old.decode("utf-8")))
    new_placeholders = set(re.findall(r"__[A-Z][A-Z0-9_]*__", text))
    assert_equal(new_placeholders, old_placeholders, "renderer placeholders changed")
    rendered = observer_render.render(
        candidate.read_bytes(), synthetic_layout(), "a" * 64, "b" * 64,
        RUN_ID, TAG, CALLER, CALL_OFFSET, PID, UID, "zero-target-preflight",
    )
    assert_true(b"BUFFER-PROTOCOL buffer-v2" in rendered)
    assert_true(b"__" not in rendered)


# ---------------------------------------------------------------------------
# Preflight license / end-to-end / verifier tests
# ---------------------------------------------------------------------------
def write_license(box, *, drop=(), **overrides):
    value = {
        "kind": "zero-target-preflight-admission",
        "protocolRevision": 3,
        "state": "approved",
        "allowedCommand": "preflight",
        "maxTargetExecutions": 0,
        "fixturesImported": 0,
        "protocolManifestSha256": box.manifest_sha(),
        "candidateManifestSha256": box.manifest_sha(),
        "sourceReviewReceiptSha256": box.review_sha(),
        "preflightId": box.preflight_id,
        "reviewer": "recorded-test-host",
    }
    value.update(overrides)
    for key in drop:
        value.pop(key, None)
    box.write_json(box.path / "codex-review" / "preflight-admission.json", value)
    return value


def actual_digests():
    parser = TOOLS / "buffer_protocol_v2.py"
    template = TOOLS / "observer_template_buffer_v2.bt"
    return (
        sha_file(parser) if parser.is_file() else "0" * 64,
        sha_file(template) if template.is_file() else "0" * 64,
    )


def write_buffer_license(box, **overrides):
    parser_sha, template_sha = actual_digests()
    values = {
        "observationProtocol": "buffer-v2",
        "framingPolicy": "end-lf-padding-v1",
        "bufferParserSha256": parser_sha,
        "bufferTemplateSha256": template_sha,
    }
    values.update(overrides)
    return write_license(box, **values)


def new_sandbox(name):
    import regression_lib
    return regression_lib.Sandbox(name)


@test("preflight-refuses-missing-wrong-protocol-or-digests-before-resources")
def preflight_refuses_missing_wrong_protocol_or_digests_before_resources():
    parser_sha, template_sha = actual_digests()
    cases = {
        "missing-protocol": ({"drop": ("observationProtocol",)}, "observation-protocol"),
        "wrong-protocol": ({"observationProtocol": "legacy"}, "observation-protocol"),
        "v1-protocol": ({"observationProtocol": "buffer-v1"}, "observation-protocol"),
        "missing-framing-policy": ({"drop": ("framingPolicy",)}, "framing-policy"),
        "wrong-framing-policy": ({"framingPolicy": "project-selected-v1"},
                                 "framing-policy"),
        "v1-parser-digest": ({"bufferParserSha256": sha_file(TOOLS / "buffer_protocol.py")},
                             "buffer-parser"),
        "v1-template-digest": ({"bufferTemplateSha256":
                                sha_file(TOOLS / "observer_template_buffer.bt")},
                               "buffer-template"),
        "missing-parser": ({"drop": ("bufferParserSha256",)}, "buffer-parser"),
        "wrong-parser": ({"bufferParserSha256": "0" * 64}, "buffer-parser"),
        "missing-template": ({"drop": ("bufferTemplateSha256",)}, "buffer-template"),
        "wrong-template": ({"bufferTemplateSha256": "0" * 64}, "buffer-template"),
    }
    results = {}
    for name, (overrides, token) in cases.items():
        box = new_sandbox("buffer-license-" + name)
        merged = {
            "observationProtocol": "buffer-v2",
            "framingPolicy": "end-lf-padding-v1",
            "bufferParserSha256": parser_sha,
            "bufferTemplateSha256": template_sha,
        }
        merged.update(overrides)
        write_license(box, **merged)
        result = box.preflight(timeout=60)
        claims = box.path / "preflight" / "claims"
        evidence = box.path / "preflight" / "evidence"
        docker_calls = len(box.docker_lines())
        results[name] = {
            "returncode": result.returncode,
            "stderr": result.stderr.strip()[-200:],
            "claimsExist": claims.exists() and any(claims.iterdir()),
            "evidenceExists": evidence.exists() and any(evidence.iterdir()),
            "dockerCalls": docker_calls,
        }
        assert_equal(result.returncode, 78, name + " returncode")
        assert_true(token in result.stderr, name + " reason: " + result.stderr[-300:])
        assert_equal(results[name]["claimsExist"], False, name + " claim created")
        assert_equal(results[name]["evidenceExists"], False, name + " evidence created")
        assert_equal(docker_calls, 0, name + " docker called")
    del results


@test("preflight-synthetic-buffer-v2-accepted-and-verifier-recomputes")
def preflight_synthetic_buffer_v1_accepted_and_verifier_recomputes():
    box = new_sandbox("buffer-preflight-e2e")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    receipt = box.read_json(box.preflight_receipt_path())
    parser_sha, template_sha = actual_digests()
    assert_equal(receipt.get("state"), "accepted")
    assert_equal(receipt.get("observationProtocol"), "buffer-v2")
    assert_equal(receipt.get("framingPolicy"), "end-lf-padding-v1")
    assert_equal(receipt.get("bufferParserSha256"), parser_sha)
    assert_equal(receipt.get("bufferTemplateSha256"), template_sha)
    assert_equal(receipt.get("frozenTemplateName"), "observer_template_buffer_v2.bt")
    assert_equal(receipt.get("frozenTemplateSha256"), template_sha)
    assert_equal(receipt.get("toolDigests", {}).get("buffer_protocol_v2.py"), parser_sha)
    assert_equal(receipt.get("toolDigests", {}).get("observer_template_buffer_v2.bt"), template_sha)
    observation = receipt.get("observation") or {}
    assert_equal(observation.get("complete"), True)
    assert_equal(observation.get("observationProtocol"), "buffer-v2")
    assert_equal(observation.get("framingPolicy"), "end-lf-padding-v1")
    assert_equal(observation.get("trailingBlankLines"), 0)
    assert_equal(observation.get("bufferParserSha256"), parser_sha)
    assert_equal(observation.get("bufferTemplateSha256"), template_sha)
    raw = (box.preflight_evidence() / "observer.raw").read_bytes()
    assert_true(b"BUFFER-PROTOCOL buffer-v2\n" in raw, "raw marker missing")
    assert_true(b"DCONSTN " in raw and b"QUALB " in raw, "buffer records missing")
    assert_true(b"DCONSTW " not in raw and b"QUALW " not in raw, "legacy records present")
    recomputed = buffer_protocol().parse_receipt(
        raw, RUN_ID, receipt["tag"], CALLER, receipt["callOffset"], receipt["targetPid"],
        UID, max_events=4, raw_truncated=False, require_events=1,
    )
    assert_equal(recomputed.get("state"), "complete", "buffer recompute state")
    assert_equal(recomputed.get("protocol"), "buffer-v2")
    assert_equal(recomputed.get("targetExecuted"), False)
    assert_equal(recomputed.get("rawSha256"), receipt["observation"]["rawSha256"])
    stored = box.read_json(box.preflight_evidence() / "observation.json")
    assert_equal(stored, recomputed, "stored observation != independent recompute")
    verified = preflight_verify().verify_preflight_evidence(
        box.path,
        box.preflight_receipt_path(),
        box.path / "codex-review" / "preflight-admission.json",
        box.path / "codex-review" / "source-review-receipt.json",
        box.path / "protocol-manifest.json",
        box.path / "tools" / "observer-profile.lock.json",
        expected_id=box.preflight_id,
    )
    assert_equal(verified["receipt"]["observationProtocol"], "buffer-v2")
    assert_equal(verified["framingPolicy"], "end-lf-padding-v1")
    assert_equal(verified["trailingBlankLines"], 0)
    assert_equal(verified["observation"]["protocol"], "buffer-v2")
    assert_equal(verified["observation"]["targetExecuted"], False)
    event = verified["observation"]["events"][0]
    assert_equal(event["callerOffset"], receipt["callOffset"])
    assert_equal(event["dynamicStructureSha256"], receipt["observation"]["structureSha256"])
    assert_equal(event["dynamicCodeSha256"], receipt["observation"]["codeSha256"])
    assert_equal(event["callerSha256"], receipt["callerSha256"])


def resign_receipt(box, mutate=None):
    path = box.preflight_receipt_path()
    receipt = box.read_json(path)
    if mutate is not None:
        mutate(receipt, box.preflight_evidence())
    box.write_json(path, receipt)
    receipt_sha = sha_file(path)
    _claim, completed_path = preflight_verify().claim_paths(box.path, box.preflight_id)
    completed = box.read_json(completed_path)
    completed["preflightReceiptSha256"] = receipt_sha
    box.write_json(completed_path, completed)
    return receipt


def verify_reason(box):
    try:
        preflight_verify().verify_preflight_evidence(
            box.path,
            box.preflight_receipt_path(),
            box.path / "codex-review" / "preflight-admission.json",
            box.path / "codex-review" / "source-review-receipt.json",
            box.path / "protocol-manifest.json",
            box.path / "tools" / "observer-profile.lock.json",
            expected_id=box.preflight_id,
        )
        return None
    except preflight_verify().PreflightError as error:
        return error.reason


@test("verifier-rejects-modified-raw-observation-and-observer-rebuild")
def verifier_rejects_modified_raw_observation_and_observer_rebuild():
    box = new_sandbox("buffer-verify-tamper")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    raw_path = box.preflight_evidence() / "observer.raw"
    original_raw = raw_path.read_bytes()

    raw_path.write_bytes(original_raw + b"\n# tampered\n")
    reason = verify_reason(box)
    raw_path.write_bytes(original_raw)
    assert_true(reason is not None and (
        "observation" in reason or "raw" in reason), "raw tamper reason: " + str(reason))

    observation_path = box.preflight_evidence() / "observation.json"
    original_observation = observation_path.read_bytes()
    observation_path.write_bytes(original_observation + b" ")
    reason = verify_reason(box)
    observation_path.write_bytes(original_observation)
    assert_true(reason is not None and (
        "observation" in reason), "stored observation tamper reason: " + str(reason))

    observer_path = box.preflight_evidence() / "observer.bt"
    original_observer = observer_path.read_bytes()

    def mutate(receipt, evidence):
        tamp = evidence / "observer.bt"
        tamp.write_bytes(original_observer + b"\n# tampered observer\n")
        tamp_sha = sha_file(tamp)
        receipt["observerTemplateSha256"] = tamp_sha
        receipt["observation"]["observerSha256"] = tamp_sha

    resign_receipt(box, mutate)
    reason = verify_reason(box)
    observer_path.write_bytes(original_observer)
    assert_equal(reason, "observer-rebuild-mismatch", "observer rebuild reason")


@test("verifier-rejects-receipt-parser-and-template-digest-mismatch")
def verifier_rejects_receipt_parser_and_template_digest_mismatch():
    box = new_sandbox("buffer-verify-digest")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    parser_sha, template_sha = actual_digests()

    resign_receipt(box, lambda receipt, evidence: receipt.__setitem__(
        "bufferParserSha256", "0" * 64))
    reason = verify_reason(box)
    assert_true(reason is not None and "parser" in reason, "parser digest reason: " + str(reason))

    resign_receipt(box, lambda receipt, evidence: (
        receipt.__setitem__("bufferParserSha256", parser_sha),
        receipt.__setitem__("bufferTemplateSha256", "0" * 64),
    ))
    reason = verify_reason(box)
    assert_true(reason is not None and "template" in reason, "template digest reason: " + str(reason))

    resign_receipt(box, lambda receipt, evidence: (
        receipt.__setitem__("bufferTemplateSha256", template_sha),
        receipt.__setitem__("frozenTemplateSha256", "0" * 64),
    ))
    reason = verify_reason(box)
    assert_true(reason is not None and "template" in reason, "frozen template reason: " + str(reason))


@test("verifier-rejects-actual-parser-and-template-file-tamper")
def verifier_rejects_actual_parser_and_template_file_tamper():
    box = new_sandbox("buffer-v2-material-tamper")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    parser_path = box.path / "tools" / "buffer_protocol_v2.py"
    template_path = box.path / "tools" / "observer_template_buffer_v2.bt"
    parser_original = parser_path.read_bytes()
    template_original = template_path.read_bytes()
    try:
        parser_path.write_bytes(parser_original + b"\n# tampered parser\n")
        reason = verify_reason(box)
        assert_true(reason is not None and (
            "manifest" in reason or "parser" in reason),
            "parser file tamper reason: " + str(reason))
    finally:
        parser_path.write_bytes(parser_original)
    try:
        template_path.write_bytes(template_original + b"\n// tampered template\n")
        reason = verify_reason(box)
        assert_true(reason is not None and (
            "manifest" in reason or "template" in reason),
            "template file tamper reason: " + str(reason))
    finally:
        template_path.write_bytes(template_original)
    assert_equal(verify_reason(box), None, "restored material should verify")


@test("legacy-and-downgraded-records-are-not-admitted-as-buffer-preflight")
def legacy_and_downgraded_records_are_not_admitted_as_buffer_preflight():
    box = new_sandbox("buffer-legacy-downgrade")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    parser_sha, template_sha = actual_digests()

    resign_receipt(box, lambda receipt, evidence: receipt.__setitem__(
        "observationProtocol", "legacy"))
    reason = verify_reason(box)
    assert_true(reason is not None and "observation-protocol" in reason,
                "receipt downgrade reason: " + str(reason))

    resign_receipt(box, lambda receipt, evidence: (
        receipt.__setitem__("observationProtocol", "buffer-v1"),
        receipt.__setitem__("bufferParserSha256", parser_sha),
        receipt.__setitem__("bufferTemplateSha256", template_sha),
    ))
    reason = verify_reason(box)
    assert_true(reason is not None and "observation-protocol" in reason,
                "v1 receipt downgrade reason: " + str(reason))

    resign_receipt(box, lambda receipt, evidence: (
        receipt.__setitem__("observationProtocol", "buffer-v2"),
        receipt.__setitem__("bufferParserSha256", parser_sha),
        receipt.__setitem__("bufferTemplateSha256", template_sha),
    ))
    assert_equal(verify_reason(box), None)
    claim_path, _completed = preflight_verify().claim_paths(box.path, box.preflight_id)
    claim = box.read_json(claim_path)
    claim["observationProtocol"] = "legacy"
    box.write_json(claim_path, claim)
    reason = verify_reason(box)
    assert_true(reason is not None and "claim-observation-protocol" in reason,
                "claim downgrade reason: " + str(reason))


@test("strict-exitcode-types-rejected-unknown-null-preserved")
def strict_exitcode_types_rejected_unknown_null_preserved():
    import preflight_diagnostics as diagnostics
    for value in (False, True, 0.0, "0"):
        assert_equal(diagnostics._known_integer(value), False, "accepted invalid returncode")
    assert_equal(diagnostics._known_integer(None), False)
    assert_equal(diagnostics._known_integer(0), True)
    assert_equal(diagnostics._known_integer(-2), True)

    for value in (False, 0.0):
        box = new_sandbox("buffer-exitcode-collector")
        write_buffer_license(box)
        result = box.preflight(timeout=180)
        assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
        resign_receipt(box, lambda receipt, evidence, value=value: receipt.__setitem__(
            "collectorExitCode", value))
        reason = verify_reason(box)
        assert_true(reason is not None and "collector-exit" in reason,
                    "collector exit type %r reason: %s" % (value, reason))

    def bad_query(name, key, receipt_field):
        def mutate(receipt, evidence):
            path = evidence / name
            value = box.read_json(path)
            value[key]["returncode"] = False
            box.write_json(path, value)
            digest = sha_file(path)
            receipt[receipt_field] = digest
            receipt["evidenceDigests"][name] = digest
        return mutate

    for name, key, receipt_field, token in (
        ("container-created.json", "createQuery", "containerCreatedSha256",
         "container-create-query"),
        ("container-pid.json", "query", "containerPidSha256", "container-pid-query"),
    ):
        box = new_sandbox("buffer-exitcode-query")
        write_buffer_license(box)
        result = box.preflight(timeout=180)
        assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
        resign_receipt(box, bad_query(name, key, receipt_field))
        reason = verify_reason(box)
        assert_true(reason is not None and token in reason,
                    "%s bool returncode reason: %s" % (name, reason))


@test("recovery-and-status-query-original-id-without-replay")
def recovery_and_status_query_original_id_without_replay():
    box = new_sandbox("buffer-recovery")
    write_buffer_license(box)
    result = box.preflight(timeout=180)
    assert_equal(result.returncode, 0, "preflight rc: " + result.stderr[-800:])
    receipt_path = box.preflight_receipt_path()
    receipt_sha = sha_file(receipt_path)
    status = box.status(box.preflight_id)
    assert_equal(status.returncode, 0, status.stdout + status.stderr)
    status_value = json.loads(status.stdout)
    assert_equal(status_value.get("state"), "completed")
    assert_equal(status_value.get("observationProtocol"), "buffer-v2")
    recover = subprocess.run(
        [sys.executable, str(box.path / "tools" / "zero_target_preflight.py"),
         "recover", "--preflight-id", box.preflight_id],
        capture_output=True, text=True, env=box.env(), timeout=120,
    )
    assert_equal(recover.returncode, 0, recover.stdout + recover.stderr)
    assert_equal(json.loads(recover.stdout).get("state"), "resources-cleared")
    assert_equal(sha_file(receipt_path), receipt_sha, "recovery rewrote receipt")
    recovery_files = sorted(box.preflight_evidence().glob("recovery-*.json"))
    assert_true(recovery_files, "recovery record missing")
    recovery = box.read_json(recovery_files[-1])
    assert_equal(recovery.get("selfCheckReplayed"), False)
    assert_equal(recovery.get("receiptAccepted"), False)
    assert_equal(recovery.get("realMachinePass"), False)

    # A historical claim without the new protocol binding stays readable in a
    # read-only status query; it is never promoted to a new buffer acceptance.
    claim_path, _completed = preflight_verify().claim_paths(box.path, box.preflight_id)
    claim = box.read_json(claim_path)
    for key in ("observationProtocol", "bufferParserSha256", "bufferTemplateSha256"):
        claim.pop(key, None)
    box.write_json(claim_path, claim)
    historical = box.status(box.preflight_id)
    assert_equal(historical.returncode, 0, historical.stdout + historical.stderr)
    assert_equal(json.loads(historical.stdout).get("state"), "completed")
    assert_equal(json.loads(historical.stdout).get("observationProtocol"), None)


@test("go-waits-for-buffer-marker-and-does-not-run-on-early-begin")
def go_waits_for_buffer_marker_and_does_not_run_on_early_begin():
    box = new_sandbox("buffer-go-marker")
    write_buffer_license(box)
    result = box.preflight(extra={"SCE_OBSERVER_WITHHOLD_MARKER": "1"}, timeout=90)
    evidence = box.preflight_evidence()
    failure = box.read_json(evidence / "failure.json") if (evidence / "failure.json").is_file() else {}
    assert_equal(result.returncode, 79)
    assert_equal(failure.get("reason"), "preflight-observer-not-armed",
                 "early GO or wrong failure: " + repr(failure.get("reason")))
    assert_equal((evidence / "preflight-receipt.json").exists(), False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "checks" / "buffer-preflight-results.json"))
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    selected = [(name, fn) for name, fn in TESTS if not args.only or args.only in name]
    if not selected:
        raise SystemExit("no tests selected")
    entries = []
    failures = []
    for name, function in selected:
        try:
            function()
            entries.append({"test": name, "passed": True})
            print("PASS " + name)
        except BaseException as error:  # noqa: BLE001
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
    payload = {
        "kind": "buffer-v2-zero-target-preflight-focused-results",
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
        "formalTargets": "0/16",
        "r3": "blocked",
        "results": entries,
        "passed": sum(1 for item in entries if item["passed"]),
        "failed": failures,
        "total": len(entries),
        "note": "Synthetic/recorded-shim tests only; no runtime observation evidence.",
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"],
                      "total": payload["total"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
