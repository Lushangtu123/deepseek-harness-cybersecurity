"""Strict buffer-v2 observer stream parser and normalizer.

This module is the buffer-v2 successor to the frozen ``buffer_protocol``
module.  It imports only the trusted sibling modules ``observation_pure`` and
``structure`` from ``tools/``.  It never adds a project/reference path to
``sys.path``, never reads a target and never executes anything.

The pinned bpftrace v0.20.2 formatter calls ``hex_format_buffer`` with
``keep_ascii=false`` and ``escape_hex=false`` for ``%rh`` (see
``format_string.cpp`` and ``printf.cpp``).  The formatter therefore emits two
lowercase hexadecimal digits per byte and exactly one ASCII space *between*
bytes; there is no trailing space.  The buffer-v2 grammar uses that exact wire
shape.  A four-byte value such as ``_run`` is written ``5f 72 75 6e``.

Grammar (one stream per observer invocation)::

    BEGIN run=<id> tag=<tag>
    BUFFER-PROTOCOL buffer-v2
    EVENT <dyn_first> <dyn_flags> <dyn_units> <caller_first> <caller_flags> <caller_units> <caller_off>
    DCODE <i> <bytehex>
    DCONST <i> n|?|i <negative> <digit>
    DCONSTN <count>                 (total dynamic constants, 0..8)
    DCONSTB <i> <length> <payload>
    DNAMEN <count>                  (total dynamic names, 0..16)
    DNAMEB <i> <length> <payload>
    QUALB <length> <payload>
    KCONSTN <count>                 (total caller constants, 0..8)
    KCONSTB <i> <length> <payload>
    KNAMEN <count>                  (total caller names, 0..16)
    KNAMEB <i> <length> <payload>
    UNSUPPORTED <reason>
    END run=<id> tag=<tag> events=<count>

For a non-empty ``<payload>`` there are exactly ``<length>`` tokens, each
matching ``[0-9a-f]{2}``, joined by exactly one ASCII space and with no
leading or trailing space.  A zero-length value is the single byte ``-`` (the
template emits no memory read for it).  Contiguous multi-byte hex, odd or
partial pairs, uppercase, ``0x`` prefixes, tabs, doubled spaces and missing or
extra tokens are all invalid.  A length of one is wire-compatible with v1, but
the required ``buffer-v2`` marker keeps the protocols distinct.

Legacy ``*W`` records and legacy string headers are rejected, so a stream
cannot mix formats.  This module is pure: synthetic parser tests are not
observed runtime evidence, and ``targetExecuted`` is always false.

Framing policy ``end-lf-padding-v1`` is tool-fixed.  The one valid ``END``
record has its normal LF terminator and may be followed by 0..8 additional LF
bytes.  Those bytes are part of ``rawBytes``/``rawSha256`` and are reported as
``trailingBlankLines`` (extra LF beyond the normal terminator).  Nine or more
extra LF bytes are invalid.  Empty lines anywhere before ``END``, spaces, TABs,
CR, records after ``END``, duplicate/missing ``END`` and an unterminated final
record remain invalid.  The trailer is validated only after the unique ``END``
and declared event count are checked; it is not a general empty-line cleanup.
"""

from __future__ import annotations

import hashlib
import re

# The frozen sibling modules are this candidate's tools/observation_pure.py and
# tools/structure.py.  The historical reference copies are never imported.
import observation_pure as _legacy
import structure

PROTOCOL = "buffer-v2"
MARKER = "BUFFER-PROTOCOL buffer-v2"
FRAMING_POLICY = "end-lf-padding-v1"
MAX_TRAILING_BLANK_LINES = 8
RECORD_NAMES = ("DCONSTB", "DNAMEB", "QUALB", "KCONSTB", "KNAMEB")
COUNT_RECORD_NAMES = ("DCONSTN", "DNAMEN", "KCONSTN", "KNAMEN")
LEGACY_BYTE_RECORDS = ("DCONSTW", "DNAMEW", "QUALW", "KCONSTW", "KNAMEW")
LEGACY_STRING_HEADERS = ("DNAME", "QUAL", "KNAME")
PAIR_RE = re.compile(r"[0-9a-f]{2}")

MAX_EVENTS = _legacy.MAX_EVENTS
MAX_STR = _legacy.MAX_STR
MAX_NAMES = _legacy.MAX_NAMES
MAX_CONSTS = _legacy.MAX_CONSTS
MAX_DYN_BYTES = _legacy.MAX_DYN_BYTES
MAX_CALLER_UNITS = _legacy.MAX_CALLER_UNITS

ParseError = _legacy.ParseError


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_payload(token: str, length: int, what: str) -> bytes:
    """Decode exactly ``length`` space-separated lowercase byte pairs.

    ``token`` is the raw remaining payload text; it is never stripped or
    normalized.  Every malformed shape becomes an explicit ``ParseError``.
    """
    if length < 0 or length > MAX_STR:
        raise ParseError(what + ":range")
    if length == 0:
        if token != "-":
            raise ParseError(what + ":zero-token")
        return b""
    if token == "-":
        raise ParseError(what + ":dash-nonzero")
    tokens = token.split(" ")
    if any(not item for item in tokens):
        # Leading, trailing or doubled ASCII spaces produce an empty token.
        raise ParseError(what + ":spacing")
    for item in tokens:
        if not PAIR_RE.fullmatch(item):
            # Covers contiguous multi-byte hex, odd/partial pairs, uppercase,
            # 0x prefixes, tabs and any other non-pair text.
            raise ParseError(what + ":hex")
    if len(tokens) != length:
        raise ParseError(what + ":length")
    payload = bytes(int(item, 16) for item in tokens)
    if not payload.isascii():
        # The frozen legacy builder decodes string entries as ASCII.  Reject
        # non-ASCII bytes at the buffer-format boundary so malformed evidence
        # returns the existing invalid receipt instead of leaking a
        # UnicodeDecodeError.  Bytes 0..127, NUL and empty strings are kept.
        raise ParseError(what + ":non-ascii")
    return payload


def _string_entry(payload: bytes, typed: bool = False) -> dict:
    entry = {
        "len": len(payload),
        "bytes": {index: value for index, value in enumerate(payload)},
    }
    if typed:
        entry["t"] = "str"
    return entry


def _add_string_map(event: dict, key: str, index: int, length: int, token: str, what: str):
    if index < 0 or index >= (MAX_NAMES if key in ("dnames", "knames") else MAX_CONSTS):
        raise ParseError(what + ":index")
    if index in event[key]:
        raise ParseError(what + ":duplicate")
    event[key][index] = _string_entry(
        _parse_payload(token, length, what), typed=key in ("dconsts", "kconsts")
    )


def _parse_const(event: dict, key: str, parts: list[str], label: str) -> None:
    if len(parts) < 2:
        raise ParseError(label + "-shape")
    index = _legacy.parse_ints([parts[0]], 1, label + "-index")[0]
    if index < 0 or index >= MAX_CONSTS or index in event[key]:
        raise ParseError(label + "-index")
    kind = parts[1]
    if kind == "n":
        if len(parts) != 2:
            raise ParseError(label + "-none-shape")
        event[key][index] = {"t": "none"}
    elif kind == "?":
        if len(parts) != 2:
            raise ParseError(label + "-unknown-shape")
        event[key][index] = {"t": "unsupported"}
    elif kind == "i":
        if len(parts) != 4:
            raise ParseError(label + "-int-shape")
        neg, digit = _legacy.parse_ints(parts[2:4], 2, label + "-int")
        if neg not in (0, 2) or digit < 0 or digit >= (1 << 30):
            raise ParseError(label + "-int-range")
        event[key][index] = {"t": "int", "v": -digit if neg else digit}
    elif kind == "s":
        # A legacy string header is a mixed-format record in buffer-v2.
        raise ParseError(label + "-legacy-string-header")
    else:
        raise ParseError(label + "-kind")


_COUNT_MAP = {
    "DCONSTN": ("dconsts", MAX_CONSTS, "dconst-count"),
    "DNAMEN": ("dnames", MAX_NAMES, "dname-count"),
    "KCONSTN": ("kconsts", MAX_CONSTS, "kconst-count"),
    "KNAMEN": ("knames", MAX_NAMES, "kname-count"),
}


def _validate_event_counts(event: dict) -> None:
    counts = event.pop("_counts", None)
    if not isinstance(counts, dict):
        raise ParseError("counts-missing")
    for record, (key, limit, label) in _COUNT_MAP.items():
        if record not in counts:
            raise ParseError(label + "-missing")
        count = counts[record]
        if count < 0 or count > limit:
            raise ParseError(label + "-range")
        if sorted(event[key]) != list(range(count)):
            raise ParseError(label + "-index-coverage")


def _parse_indexed_string(line: str, opcode: str, label: str):
    """Split ``<op> <i> <len> <payload>`` without touching the payload."""
    if not line.startswith(opcode + " "):
        raise ParseError(label + "-shape")
    fields = line[len(opcode) + 1:].split(" ", 2)
    if len(fields) != 3:
        raise ParseError(label + "-shape")
    index = _legacy.parse_ints([fields[0]], 1, label + "-index")[0]
    length = _legacy.parse_ints([fields[1]], 1, label + "-length")[0]
    return index, length, fields[2]


def _parse_plain_string(line: str, opcode: str, label: str):
    """Split ``QUALB <len> <payload>`` without touching the payload."""
    if not line.startswith(opcode + " "):
        raise ParseError(label + "-shape")
    fields = line[len(opcode) + 1:].split(" ", 1)
    if len(fields) != 2:
        raise ParseError(label + "-shape")
    length = _legacy.parse_ints([fields[0]], 1, label + "-length")[0]
    return length, fields[1]


def _strict_lines(text: str) -> tuple[list[str], int]:
    """Split on LF only and report the number of trailing LF bytes.

    The final END record has one normal LF terminator; additional trailing LF
    bytes are counted here and validated later, after the unique END and event
    counts are checked.  No line is stripped: an empty line inside the stream,
    CR/TAB, leading/trailing spaces and any non-LF trailer remain invalid.
    """
    raw_lines = text.split("\n")
    last_content = None
    for index, line in enumerate(raw_lines):
        if line:
            last_content = index
    if last_content is None:
        raise ParseError("stream-empty")
    lines = raw_lines[:last_content + 1]
    trailing_lf = len(raw_lines) - last_content - 1
    for line in lines:
        if not line:
            raise ParseError("blank-line")
        if line.startswith(" ") or line.endswith(" "):
            raise ParseError("line-spacing")
        if "\t" in line or "\r" in line:
            raise ParseError("line-control")
    return lines, trailing_lf


def parse_output(
    raw,
    run_id,
    tag,
    caller_path,
    call_offset,
    max_events,
    raw_truncated=False,
    framing_policy=FRAMING_POLICY,
):
    """Parse one buffer-v2 stream into legacy-shaped raw event groups."""
    details = {
        "protocol": PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "trailingBlankLines": None,
        "marker": None,
        "markerCount": 0,
        "beginCount": 0,
        "endCount": 0,
        "lineCount": 0,
        "begin": None,
        "end": None,
        "endEvents": None,
        "trailingAfterEnd": False,
        "rawBytes": len(raw) if isinstance(raw, bytes) else None,
        "rawSha256": sha256_bytes(raw) if isinstance(raw, bytes) else None,
        "recordCounts": {name: 0 for name in RECORD_NAMES},
    }
    errors: list[str] = []
    if framing_policy != FRAMING_POLICY:
        return None, ["framing-policy"], details
    if raw_truncated:
        return None, ["raw-truncated"], details
    try:
        text = raw.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        return None, ["raw-not-ascii"], details
    try:
        lines, trailing_lf = _strict_lines(text)
    except ParseError as error:
        return None, [type(error).__name__ + ":" + str(error)], details
    details["lineCount"] = len(lines)
    if not lines or not lines[0].startswith("BEGIN "):
        return None, ["begin-missing"], details
    begin_lines = [index for index, line in enumerate(lines) if line.startswith("BEGIN ")]
    details["beginCount"] = len(begin_lines)
    if len(begin_lines) != 1 or begin_lines[0] != 0:
        return None, ["begin-duplicate"], details
    end_lines = [index for index, line in enumerate(lines) if line.startswith("END ")]
    details["endCount"] = len(end_lines)
    if not end_lines:
        return None, ["end-missing"], details
    if len(end_lines) != 1:
        return None, ["end-duplicate"], details
    if end_lines[0] != len(lines) - 1:
        details["trailingAfterEnd"] = True
        return None, ["trailing-after-end"], details

    begin = lines[0][len("BEGIN "):]
    details["begin"] = begin
    if begin != "run=%s tag=%s" % (run_id, tag):
        return None, ["begin-mismatch"], details
    end_parts = lines[-1][len("END "):].split(" ")
    details["end"] = lines[-1][len("END "):]
    if len(end_parts) != 3 or end_parts[0] != "run=" + run_id or end_parts[1] != "tag=" + tag:
        return None, ["end-mismatch"], details
    if not end_parts[2].startswith("events=") or not re.fullmatch(r"\d+", end_parts[2][7:]):
        return None, ["end-events"], details
    end_events = int(end_parts[2][7:])
    details["endEvents"] = end_events

    marker_lines = [
        index for index, line in enumerate(lines) if line.startswith("BUFFER-PROTOCOL")
    ]
    details["markerCount"] = len(marker_lines)
    if not marker_lines:
        return None, ["marker-missing"], details
    if len(marker_lines) != 1:
        return None, ["marker-duplicate"], details
    if marker_lines[0] != 1:
        return None, ["marker-position"], details
    if lines[1] != MARKER:
        return None, ["marker-invalid"], details
    details["marker"] = lines[1]

    events = []
    current = None
    try:
        for line in lines[2:end_lines[0]]:
            if line.startswith("EVENT "):
                if current is not None:
                    _validate_event_counts(current)
                    events.append(current)
                current = _legacy.new_event()
                current["_counts"] = {}
                values = _legacy.parse_ints(
                    line[len("EVENT "):].split(" "), 7, "event"
                )
                (
                    current["dyn_first"],
                    current["dyn_flags"],
                    current["dyn_units"],
                    current["caller_first"],
                    current["caller_flags"],
                    current["caller_units"],
                    current["caller_off"],
                ) = values
                continue
            if current is None:
                raise ParseError("field-before-event")
            if line.startswith("UNSUPPORTED "):
                reason = line[len("UNSUPPORTED "):]
                if not reason or len(reason) > 64:
                    raise ParseError("unsupported-reason")
                current["unsupported"].append(reason)
                continue
            parts = line.split(" ")
            opcode = parts[0]
            if opcode in LEGACY_BYTE_RECORDS:
                raise ParseError("mixed-legacy-byte-record:" + opcode)
            if opcode in LEGACY_STRING_HEADERS:
                raise ParseError("mixed-legacy-string-record:" + opcode)
            if opcode in _COUNT_MAP:
                if len(parts) != 2:
                    raise ParseError(opcode.lower() + "-shape")
                count = _legacy.parse_ints([parts[1]], 1, opcode.lower())[0]
                if opcode in current["_counts"]:
                    raise ParseError(opcode.lower() + "-duplicate")
                current["_counts"][opcode] = count
            elif opcode == "DCODE":
                index, value = _legacy.parse_byte(parts[1:], "dcode")
                if index in current["dcode"]:
                    raise ParseError("dcode-duplicate")
                current["dcode"][index] = value
            elif opcode == "DCONST":
                _parse_const(current, "dconsts", parts[1:], "dconst")
            elif opcode == "KCONST":
                _parse_const(current, "kconsts", parts[1:], "kconst")
            elif opcode == "DCONSTB":
                index, length, token = _parse_indexed_string(line, opcode, "dconstb")
                _add_string_map(current, "dconsts", index, length, token, "dconstb")
                details["recordCounts"]["DCONSTB"] += 1
            elif opcode == "DNAMEB":
                index, length, token = _parse_indexed_string(line, opcode, "dnameb")
                _add_string_map(current, "dnames", index, length, token, "dnameb")
                details["recordCounts"]["DNAMEB"] += 1
            elif opcode == "QUALB":
                length, token = _parse_plain_string(line, opcode, "qualb")
                if current["qual"]:
                    raise ParseError("qualb-duplicate")
                current["qual"] = _string_entry(_parse_payload(token, length, "qualb"))
                details["recordCounts"]["QUALB"] += 1
            elif opcode == "KCONSTB":
                index, length, token = _parse_indexed_string(line, opcode, "kconstb")
                _add_string_map(current, "kconsts", index, length, token, "kconstb")
                details["recordCounts"]["KCONSTB"] += 1
            elif opcode == "KNAMEB":
                index, length, token = _parse_indexed_string(line, opcode, "knameb")
                _add_string_map(current, "knames", index, length, token, "knameb")
                details["recordCounts"]["KNAMEB"] += 1
            else:
                raise ParseError("unknown-opcode:" + opcode[:16])
        if current is not None:
            _validate_event_counts(current)
            events.append(current)
    except (ParseError, ValueError, KeyError) as error:
        errors.append(type(error).__name__ + ":" + str(error))
        return None, errors, details
    if len(events) > max_events:
        errors.append("event-count-overflow")
    if end_events != len(events):
        errors.append("event-count-mismatch")
    # The trailer is classified only after the unique END and the declared
    # event count have been checked.  One LF terminates END; at most eight
    # further LF bytes are the bounded framing allowance.  They are not
    # stripped from the raw digest, and no other trailer byte is permitted.
    if trailing_lf == 0:
        errors.append("end-unterminated")
    elif trailing_lf - 1 > MAX_TRAILING_BLANK_LINES:
        errors.append("trailing-lf-overflow")
    else:
        details["trailingBlankLines"] = trailing_lf - 1
    return events, errors, details


def parse_receipt(
    raw,
    run_id,
    tag,
    caller_path,
    call_offset,
    target_pid,
    target_uid,
    max_events=MAX_EVENTS,
    raw_truncated=False,
    require_events=None,
    forced_stop=False,
    drain_incomplete=False,
    framing_policy=FRAMING_POLICY,
):
    """Recompute one buffer-v2 receipt into the legacy canonical event shape."""
    if type(target_pid) is not int or target_pid <= 0 or type(target_uid) is not int or target_uid < 0:
        return {
            "state": "invalid",
            "events": [],
            "errors": ["target-identity"],
            "framingPolicy": FRAMING_POLICY,
            "trailingBlankLines": None,
            "rawBytes": len(raw) if isinstance(raw, bytes) else None,
            "rawSha256": sha256_bytes(raw) if isinstance(raw, bytes) else None,
        }
    receipt = {
        "version": 2,
        "kind": "dynstruct-observation",
        "protocol": PROTOCOL,
        "framingPolicy": FRAMING_POLICY,
        "runId": run_id,
        "tag": tag,
        "targetPid": target_pid,
        "targetUid": target_uid,
        "rawSha256": sha256_bytes(raw),
        "rawBytes": len(raw),
        "callerPath": caller_path,
        "callOffset": call_offset,
        "state": "invalid",
        "events": [],
        "errors": [],
        # This pure parser makes no runtime claim.  A real collector must supply
        # its own execution/target evidence; synthetic tests must not.
        "targetExecuted": False,
        "targetSelfReportUsed": False,
        "rawTruncated": bool(raw_truncated),
    }
    events, errors, details = parse_output(
        raw, run_id, tag, caller_path, call_offset, max_events, raw_truncated,
        framing_policy=framing_policy,
    )
    receipt.update(details)
    if forced_stop:
        receipt["state"] = "invalid"
        receipt["errors"] = ["forced-stop"]
        return receipt
    if drain_incomplete:
        receipt["state"] = "invalid"
        receipt["errors"] = ["drain-incomplete"]
        return receipt
    if events is None:
        receipt["errors"] = errors
        return receipt
    built = []
    for index, event in enumerate(events):
        try:
            item = _legacy.build_event(event, caller_path)
        except (ParseError, structure.StructureUnsupported) as error:
            errors.append("event-%d:%s" % (index, error))
            continue
        if item["callerOffset"] != call_offset:
            errors.append("event-%d:caller-offset" % index)
            continue
        built.append(item)
    receipt["events"] = built
    receipt["errors"] = errors
    if require_events is not None and len(built) != require_events:
        errors.append("required-event-count:%d" % require_events)
        receipt["errors"] = errors
    if not errors and len(built) == len(events):
        receipt["state"] = "complete"
    return receipt
