"""EXPERIMENTAL buffer-v1 observer stream parser and normalizer.

This candidate copy imports the frozen sibling modules ``observation_pure`` and
``structure`` from ``tools/``.  No reference/project path is added to sys.path.

The grammar is a versioned, whole-string alternative to the legacy per-byte
``*W`` records.  It is intentionally *not* accepted by the frozen legacy parser
in ``inputs/legacy/observation_pure.py``; that module is never modified.

Grammar (one stream per observer invocation)::

    BEGIN run=<id> tag=<tag>
    BUFFER-PROTOCOL buffer-v1
    EVENT <dyn_first> <dyn_flags> <dyn_units> <caller_first> <caller_flags> <caller_units> <caller_off>
    DCODE <i> <bytehex>
    DCONST <i> n|?|i <negative> <digit>
    DCONSTN <count>                 (total dynamic constants, 0..8)
    DCONSTB <i> <length> <hex-or-dash>
    DNAMEN <count>                  (total dynamic names, 0..16)
    DNAMEB <i> <length> <hex-or-dash>
    QUALB <length> <hex-or-dash>
    KCONSTN <count>                 (total caller constants, 0..8)
    KCONSTB <i> <length> <hex-or-dash>
    KNAMEN <count>                  (total caller names, 0..16)
    KNAMEB <i> <length> <hex-or-dash>
    UNSUPPORTED <reason>
    END run=<id> tag=<tag> events=<count>

``<hex-or-dash>`` is lowercase even-length hexadecimal whose decoded length is
exactly ``<length>`` (0..64).  A zero-length value is the single byte ``-`` and
must not trigger a memory read in the producer.  Legacy ``*W`` records and
legacy string headers are rejected, so a stream cannot mix formats.

This module is pure: it reads no target, runs no process and imports only the
frozen parser/structure references.  Synthetic format tests are not observed
runtime evidence.
"""

from __future__ import annotations

import hashlib
import re

# The frozen sibling modules are this candidate's tools/observation_pure.py and
# tools/structure.py.  The historical reference copies are never imported.
import observation_pure as _legacy
import structure

PROTOCOL = "buffer-v1"
MARKER = "BUFFER-PROTOCOL buffer-v1"
RECORD_NAMES = ("DCONSTB", "DNAMEB", "QUALB", "KCONSTB", "KNAMEB")
COUNT_RECORD_NAMES = ("DCONSTN", "DNAMEN", "KCONSTN", "KNAMEN")
LEGACY_BYTE_RECORDS = ("DCONSTW", "DNAMEW", "QUALW", "KCONSTW", "KNAMEW")
LEGACY_STRING_HEADERS = ("DNAME", "QUAL", "KNAME")
HEX_RE = re.compile(r"[0-9a-f]+")

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
    if length < 0 or length > MAX_STR:
        raise ParseError(what + ":range")
    if length == 0:
        if token != "-":
            raise ParseError(what + ":zero-token")
        return b""
    if token == "-":
        raise ParseError(what + ":dash-nonzero")
    if len(token) % 2:
        raise ParseError(what + ":odd")
    if len(token) != length * 2:
        raise ParseError(what + ":length")
    if not HEX_RE.fullmatch(token):
        raise ParseError(what + ":hex")
    payload = bytes.fromhex(token)
    if not payload.isascii():
        # The frozen legacy builder decodes string entries as ASCII.  Reject
        # non-ASCII bytes here, at the buffer-format boundary, so malformed
        # evidence returns the existing invalid receipt instead of leaking a
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
        # A legacy string header is a mixed-format record in buffer-v1.
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


def parse_output(
    raw,
    run_id,
    tag,
    caller_path,
    call_offset,
    max_events,
    raw_truncated=False,
):
    """Parse one buffer-v1 stream into legacy-shaped raw event groups."""
    details = {
        "protocol": PROTOCOL,
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
    if raw_truncated:
        return None, ["raw-truncated"], details
    try:
        text = raw.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        return None, ["raw-not-ascii"], details
    lines = [line for line in text.splitlines() if line.strip()]
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
            if not line:
                continue
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
                if len(parts) != 4:
                    raise ParseError("dconstb-shape")
                index = _legacy.parse_ints([parts[1]], 1, "dconstb-index")[0]
                length = _legacy.parse_ints([parts[2]], 1, "dconstb-length")[0]
                _add_string_map(current, "dconsts", index, length, parts[3], "dconstb")
                details["recordCounts"]["DCONSTB"] += 1
            elif opcode == "DNAMEB":
                if len(parts) != 4:
                    raise ParseError("dnameb-shape")
                index = _legacy.parse_ints([parts[1]], 1, "dnameb-index")[0]
                length = _legacy.parse_ints([parts[2]], 1, "dnameb-length")[0]
                _add_string_map(current, "dnames", index, length, parts[3], "dnameb")
                details["recordCounts"]["DNAMEB"] += 1
            elif opcode == "QUALB":
                if len(parts) != 3:
                    raise ParseError("qualb-shape")
                length = _legacy.parse_ints([parts[1]], 1, "qualb-length")[0]
                if current["qual"]:
                    raise ParseError("qualb-duplicate")
                current["qual"] = _string_entry(_parse_payload(parts[2], length, "qualb"))
                details["recordCounts"]["QUALB"] += 1
            elif opcode == "KCONSTB":
                if len(parts) != 4:
                    raise ParseError("kconstb-shape")
                index = _legacy.parse_ints([parts[1]], 1, "kconstb-index")[0]
                length = _legacy.parse_ints([parts[2]], 1, "kconstb-length")[0]
                _add_string_map(current, "kconsts", index, length, parts[3], "kconstb")
                details["recordCounts"]["KCONSTB"] += 1
            elif opcode == "KNAMEB":
                if len(parts) != 4:
                    raise ParseError("knameb-shape")
                index = _legacy.parse_ints([parts[1]], 1, "knameb-index")[0]
                length = _legacy.parse_ints([parts[2]], 1, "knameb-length")[0]
                _add_string_map(current, "knames", index, length, parts[3], "knameb")
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
):
    """Recompute one buffer-v1 receipt into the legacy canonical event shape."""
    if type(target_pid) is not int or target_pid <= 0 or type(target_uid) is not int or target_uid < 0:
        return {
            "state": "invalid",
            "events": [],
            "errors": ["target-identity"],
            "rawBytes": len(raw) if isinstance(raw, bytes) else None,
            "rawSha256": sha256_bytes(raw) if isinstance(raw, bytes) else None,
        }
    receipt = {
        "version": 2,
        "kind": "dynstruct-observation",
        "protocol": PROTOCOL,
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
        raw, run_id, tag, caller_path, call_offset, max_events, raw_truncated
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
