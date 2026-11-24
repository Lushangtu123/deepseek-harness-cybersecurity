#!/usr/bin/env python3
"""Single trusted parse function for one raw bpftrace observer stream.

The collector, the preflight verifier, the formal runner and the judge all call
``parse_receipt`` with the bytes that this invocation captured.  No caller may
substitute a previously written ``observation.json``: the receipt is always
recomputed from the supplied raw bytes.

The grammar is the frozen one emitted by ``tools/observer_template.bt``.  Any
deviation is an explicit error.  This module is pure: it never reads a target,
never runs a process and never imports a fixture.
"""
import hashlib
import re

import structure

HASH_RE = re.compile(r"[a-f0-9]{64}")
HEX_RE = re.compile(r"[a-f0-9]+")
MAX_EVENTS = 4
MAX_STR = structure.MAX_STRING_BYTES
MAX_NAMES = structure.MAX_NAMES
MAX_CONSTS = structure.MAX_CONSTS
MAX_DYN_BYTES = 2 * 64
MAX_CALLER_UNITS = 512


class ParseError(Exception):
    pass


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def parse_ints(parts, count, what):
    if len(parts) != count:
        raise ParseError(what + ":field-count")
    values = []
    for part in parts:
        if not re.fullmatch(r"-?\d+", part):
            raise ParseError(what + ":integer")
        values.append(int(part, 10))
    return values


def parse_byte(parts, what):
    if len(parts) != 2:
        raise ParseError(what + ":shape")
    index = parse_ints([parts[0]], 1, what + ":index")[0]
    if not HEX_RE.fullmatch(parts[1]) or len(parts[1]) > 2:
        raise ParseError(what + ":hex")
    value = int(parts[1], 16)
    if value > 255:
        raise ParseError(what + ":range")
    return index, value


def new_event():
    return {
        "dyn_first": None,
        "dyn_flags": None,
        "dyn_units": None,
        "caller_first": None,
        "caller_flags": None,
        "caller_units": None,
        "caller_off": None,
        "dcode": {},
        "dnames": {},
        "dconsts": {},
        "qual": {},
        "knames": {},
        "kconsts": {},
        "unsupported": [],
    }


def parse_output(raw, run_id, tag, caller_path, call_offset, max_events, raw_truncated=False):
    """Parse the raw stream into raw event groups plus explicit errors."""
    details = {
        "beginCount": 0,
        "endCount": 0,
        "lineCount": 0,
        "begin": None,
        "end": None,
        "endEvents": None,
        "trailingAfterEnd": False,
        "rawBytes": len(raw) if isinstance(raw, bytes) else None,
        "rawSha256": sha256_bytes(raw) if isinstance(raw, bytes) else None,
    }
    errors = []
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
    events = []
    current = None
    try:
        for line in lines[1:end_lines[0]]:
            if not line:
                continue
            if line.startswith("EVENT "):
                if current is not None:
                    events.append(current)
                current = new_event()
                values = parse_ints(line[len("EVENT "):].split(" "), 7, "event")
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
            if opcode == "DCODE":
                index, value = parse_byte(parts[1:], "dcode")
                if index in current["dcode"]:
                    raise ParseError("dcode-duplicate")
                current["dcode"][index] = value
            elif opcode == "DNAME":
                if len(parts) != 3:
                    raise ParseError("dname-shape")
                index, length = parse_ints(parts[1:], 2, "dname")
                if index < 0 or index >= MAX_NAMES or length < 0 or length > MAX_STR:
                    raise ParseError("dname-range")
                if index in current["dnames"]:
                    raise ParseError("dname-duplicate")
                current["dnames"][index] = {"len": length, "bytes": {}}
            elif opcode == "DNAMEW":
                if len(parts) != 4:
                    raise ParseError("dnamew-shape")
                index, sub = parse_ints(parts[1:3], 2, "dnamew")
                value = int(parts[3], 16) if HEX_RE.fullmatch(parts[3]) and len(parts[3]) <= 2 else None
                if value is None or value > 255:
                    raise ParseError("dnamew-hex")
                entry = current["dnames"].get(index)
                if entry is None or sub < 0 or sub >= entry["len"] or sub in entry["bytes"]:
                    raise ParseError("dnamew-order")
                entry["bytes"][sub] = value
            elif opcode == "DCONST":
                if len(parts) < 3:
                    raise ParseError("dconst-shape")
                index = parse_ints([parts[1]], 1, "dconst-index")[0]
                if index < 0 or index >= MAX_CONSTS or index in current["dconsts"]:
                    raise ParseError("dconst-index")
                kind = parts[2]
                if kind == "n":
                    if len(parts) != 3:
                        raise ParseError("dconst-none-shape")
                    current["dconsts"][index] = {"t": "none"}
                elif kind == "?":
                    if len(parts) != 3:
                        raise ParseError("dconst-unknown-shape")
                    current["dconsts"][index] = {"t": "unsupported"}
                elif kind == "i":
                    if len(parts) != 5:
                        raise ParseError("dconst-int-shape")
                    neg, digit = parse_ints(parts[3:5], 2, "dconst-int")
                    if neg not in (0, 2) or digit < 0 or digit >= (1 << 30):
                        raise ParseError("dconst-int-range")
                    current["dconsts"][index] = {"t": "int", "v": -digit if neg else digit}
                elif kind == "s":
                    if len(parts) != 4:
                        raise ParseError("dconst-str-shape")
                    length = parse_ints([parts[3]], 1, "dconst-str")[0]
                    if length < 0 or length > MAX_STR:
                        raise ParseError("dconst-str-range")
                    current["dconsts"][index] = {"t": "str", "len": length, "bytes": {}}
                else:
                    raise ParseError("dconst-kind")
            elif opcode == "DCONSTW":
                if len(parts) != 4:
                    raise ParseError("dconstw-shape")
                index, sub = parse_ints(parts[1:3], 2, "dconstw")
                value = int(parts[3], 16) if HEX_RE.fullmatch(parts[3]) and len(parts[3]) <= 2 else None
                entry = current["dconsts"].get(index)
                if value is None or value > 255 or entry is None or entry.get("t") != "str":
                    raise ParseError("dconstw")
                if sub < 0 or sub >= entry["len"] or sub in entry["bytes"]:
                    raise ParseError("dconstw-order")
                entry["bytes"][sub] = value
            elif opcode == "QUAL":
                if len(parts) != 2:
                    raise ParseError("qual-shape")
                length = parse_ints(parts[1:], 1, "qual")[0]
                if current["qual"] or length < 0 or length > MAX_STR:
                    raise ParseError("qual-range")
                current["qual"] = {"len": length, "bytes": {}}
            elif opcode == "QUALW":
                if len(parts) != 3:
                    raise ParseError("qualw-shape")
                sub = parse_ints(parts[1:2], 1, "qualw")[0]
                value = int(parts[2], 16) if HEX_RE.fullmatch(parts[2]) and len(parts[2]) <= 2 else None
                if value is None or value > 255 or not current["qual"]:
                    raise ParseError("qualw")
                if sub < 0 or sub >= current["qual"]["len"] or sub in current["qual"]["bytes"]:
                    raise ParseError("qualw-order")
                current["qual"]["bytes"][sub] = value
            elif opcode in {"KNAME", "KCONST", "KCONSTW", "KNAMEW"}:
                mapped = {
                    "KNAME": "DNAME",
                    "KNAMEW": "DNAMEW",
                    "KCONST": "DCONST",
                    "KCONSTW": "DCONSTW",
                }[opcode]
                sub_event = {"knames": current["knames"], "kconsts": current["kconsts"]}
                _parse_into(sub_event, mapped + " " + " ".join(parts[1:]))
            else:
                raise ParseError("unknown-opcode:" + opcode[:16])
        if current is not None:
            events.append(current)
    except (ParseError, ValueError, KeyError) as error:
        errors.append(type(error).__name__ + ":" + str(error))
        return None, errors, details
    if len(events) > max_events:
        errors.append("event-count-overflow")
    if end_events != len(events):
        errors.append("event-count-mismatch")
    return events, errors, details


def _parse_into(event, line):
    parts = line.split(" ")
    opcode = parts[0]
    if opcode == "DNAME":
        if len(parts) != 3:
            raise ParseError("kname-shape")
        index, length = parse_ints(parts[1:], 2, "kname")
        if index < 0 or index >= MAX_NAMES or length < 0 or length > MAX_STR:
            raise ParseError("kname-range")
        event["knames"][index] = {"len": length, "bytes": {}}
    elif opcode == "DNAMEW":
        if len(parts) != 4:
            raise ParseError("knamew-shape")
        index, sub = parse_ints(parts[1:3], 2, "knamew")
        value = int(parts[3], 16) if HEX_RE.fullmatch(parts[3]) and len(parts[3]) <= 2 else None
        entry = event["knames"].get(index)
        if value is None or value > 255 or entry is None or sub < 0 or sub >= entry["len"] or sub in entry["bytes"]:
            raise ParseError("knamew")
        entry["bytes"][sub] = value
    elif opcode == "DCONST":
        if len(parts) < 3:
            raise ParseError("kconst-shape")
        index = parse_ints([parts[1]], 1, "kconst-index")[0]
        if index < 0 or index >= MAX_CONSTS or index in event["kconsts"]:
            raise ParseError("kconst-index")
        kind = parts[2]
        if kind == "n" and len(parts) == 3:
            event["kconsts"][index] = {"t": "none"}
        elif kind == "?" and len(parts) == 3:
            event["kconsts"][index] = {"t": "unsupported"}
        elif kind == "i" and len(parts) == 5:
            neg, digit = parse_ints(parts[3:5], 2, "kconst-int")
            if neg not in (0, 2) or digit < 0 or digit >= (1 << 30):
                raise ParseError("kconst-int-range")
            event["kconsts"][index] = {"t": "int", "v": -digit if neg else digit}
        elif kind == "s" and len(parts) == 4:
            length = parse_ints([parts[3]], 1, "kconst-str")[0]
            if length < 0 or length > MAX_STR:
                raise ParseError("kconst-str-range")
            event["kconsts"][index] = {"t": "str", "len": length, "bytes": {}}
        else:
            raise ParseError("kconst-kind")
    elif opcode == "DCONSTW":
        if len(parts) != 4:
            raise ParseError("kconstw-shape")
        index, sub = parse_ints(parts[1:3], 2, "kconstw")
        value = int(parts[3], 16) if HEX_RE.fullmatch(parts[3]) and len(parts[3]) <= 2 else None
        entry = event["kconsts"].get(index)
        if value is None or value > 255 or entry is None or entry.get("t") != "str":
            raise ParseError("kconstw")
        if sub < 0 or sub >= entry["len"] or sub in entry["bytes"]:
            raise ParseError("kconstw-order")
        entry["bytes"][sub] = value
    else:
        raise ParseError("k-opcode")


def require_map(mapping, count, what):
    if sorted(mapping) != list(range(count)):
        raise ParseError(what + ":indices")
    for index in range(count):
        need = mapping[index].get("len") if "len" in mapping[index] else None
        if need is not None:
            if sorted(mapping[index]["bytes"]) != list(range(need)):
                raise ParseError(what + ":bytes")
        if mapping[index].get("t") == "str":
            if sorted(mapping[index]["bytes"]) != list(range(mapping[index]["len"])):
                raise ParseError(what + ":str-bytes")
    return [mapping[index] for index in range(count)]


def decode_string(entry):
    return bytes(entry["bytes"][index] for index in range(entry["len"])).decode("ascii")


def build_event(event, caller_path):
    if event["unsupported"]:
        raise ParseError("unsupported:" + event["unsupported"][0])
    for key in ("dyn_first", "dyn_flags", "dyn_units", "caller_first", "caller_flags", "caller_units", "caller_off"):
        if event[key] is None:
            raise ParseError("event-field-missing:" + key)
    if event["dyn_units"] < 1 or event["dyn_units"] > 64:
        raise ParseError("dyn-units")
    if event["caller_units"] < 1 or event["caller_units"] > MAX_CALLER_UNITS:
        raise ParseError("caller-units")
    code_len = event["dyn_units"] * 2
    if code_len > MAX_DYN_BYTES:
        raise ParseError("dyn-bytes")
    if sorted(event["dcode"]) != list(range(code_len)):
        raise ParseError("dcode-coverage")
    code = bytes(event["dcode"][index] for index in range(code_len))
    names = [{"t": "str", "v": decode_string(entry)} for entry in require_map(event["dnames"], len(event["dnames"]), "dname")]
    consts = []
    for entry in require_map(event["dconsts"], len(event["dconsts"]), "dconst"):
        if entry["t"] == "str":
            consts.append({"t": "str", "v": decode_string(entry)})
        elif entry["t"] == "int":
            consts.append({"t": "int", "v": entry["v"]})
        elif entry["t"] == "none":
            consts.append({"t": "none"})
        else:
            raise ParseError("dconst-unsupported")
    if not event["qual"]:
        raise ParseError("qual-missing")
    qualname = decode_string(event["qual"])
    caller_names = [{"t": "str", "v": decode_string(entry)} for entry in require_map(event["knames"], len(event["knames"]), "kname")]
    caller_consts = []
    for entry in require_map(event["kconsts"], len(event["kconsts"]), "kconst"):
        if entry["t"] == "str":
            caller_consts.append({"t": "str", "v": decode_string(entry)})
        elif entry["t"] == "int":
            caller_consts.append({"t": "int", "v": entry["v"]})
        elif entry["t"] == "none":
            caller_consts.append({"t": "none"})
        else:
            raise ParseError("kconst-unsupported")
    dynamic_capture = {
        "filename": structure.DYNAMIC_FILENAME,
        "firstlineno": event["dyn_first"],
        "flags": event["dyn_flags"],
        "codeHex": code.hex(),
        "codeBytes": len(code),
        "names": names,
        "consts": consts,
    }
    caller_capture = {
        "schema": structure.SCHEMA,
        "kind": "caller-code-object",
        "filename": caller_path,
        "qualname": qualname,
        "firstlineno": event["caller_first"],
        "flags": event["caller_flags"],
        "codeUnits": event["caller_units"],
        "names": caller_names,
        "consts": caller_consts,
    }
    dynamic = structure.structure_from_capture(dynamic_capture)
    caller = structure.caller_descriptor_from_capture(caller_capture)
    return {
        "callerOffset": event["caller_off"],
        "dynamicStructure": dynamic,
        "dynamicStructureSha256": structure.structure_digest(dynamic),
        "dynamicCodeSha256": structure.code_digest_from_structure(dynamic),
        "callerDescriptor": caller,
        "callerSha256": structure.structure_digest(caller),
    }


def parse_receipt(raw, run_id, tag, caller_path, call_offset, target_pid, target_uid,
                  max_events=MAX_EVENTS, raw_truncated=False, require_events=None,
                  forced_stop=False, drain_incomplete=False):
    """Recompute one observation receipt from the exact bytes supplied.

    The returned ``state`` is ``complete`` only when the stream is structurally
    complete, every event parses, and every event carries the expected caller
    offset.  It is never taken from an older file.
    """
    if type(target_pid) is not int or target_pid <= 0 or type(target_uid) is not int or target_uid < 0:
        return {"state": "invalid", "events": [], "errors": ["target-identity"],
                "rawBytes": len(raw) if isinstance(raw, bytes) else None,
                "rawSha256": sha256_bytes(raw) if isinstance(raw, bytes) else None}
    receipt = {
        "version": 2,
        "kind": "dynstruct-observation",
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
        "targetExecuted": True,
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
            item = build_event(event, caller_path)
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
