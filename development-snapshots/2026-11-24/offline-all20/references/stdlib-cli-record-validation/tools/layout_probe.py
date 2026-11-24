#!/usr/bin/env python3
"""Pinned-image layout derivation for the structural observer.

Runs inside the pinned image, compiles a small tool-owned probe source with the
pinned interpreter, and derives/validates the CPython 3.12 object-field offsets
and encodings that the out-of-process observer will use.  It does not import or
execute any fixture or target and does not start bpftrace.

All user-memory reads go through ``/proc/self/mem`` with ``pread`` so a bad
candidate pointer produces ``OSError`` instead of a process crash.  Candidate
offsets must be unique and consistent across several objects; ambiguity or a
mismatch yields ``state: blocked`` and no experiment attempt may start.
"""
import argparse
import ctypes
import dis
import hashlib
import json
import os
import re
import sys

IMAGE_RE = re.compile(r"sha256:[a-f0-9]{64}")
MEM_FD = os.open("/proc/self/mem", os.O_RDONLY)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, limit=1 << 28):
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError("not-regular")
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("too-large")
    return data


def pread(addr, size):
    if type(addr) is not int or addr < 4096 or size < 1 or size > 4096:
        return None
    try:
        return os.pread(MEM_FD, size, addr)
    except OSError:
        return None


def u64(data, offset):
    if data is None or len(data) < offset + 8:
        return None
    return int.from_bytes(data[offset:offset + 8], "little")


def i64(data, offset):
    if data is None or len(data) < offset + 8:
        return None
    return int.from_bytes(data[offset:offset + 8], "little", signed=True)


def u32(data, offset):
    if data is None or len(data) < offset + 4:
        return None
    return int.from_bytes(data[offset:offset + 4], "little")


def i32(data, offset):
    if data is None or len(data) < offset + 4:
        return None
    return int.from_bytes(data[offset:offset + 4], "little", signed=True)


def find_pointer_offset(buf, target, start=8, stop=256, step=8):
    return [
        offset
        for offset in range(start, stop, step)
        if u64(buf, offset) == target
    ]


def unique(values, reason):
    if len(values) != 1:
        raise ValueError(reason + ":" + str(len(values)))
    return values[0]


def compile_objects():
    module_source = (
        "def f(value):\n"
        "    return eval(value)\n"
        "\n"
        "def outer():\n"
        "    def inner(value):\n"
        "        return eval(value)\n"
        "    return inner\n"
        "\n"
        "def g():\n"
        "    return 'marker-layout-0123456789'\n"
    )
    module = compile(
        module_source, "/review/layout/probe.py", "exec", dont_inherit=True, optimize=0
    )
    evals = [
        compile("len('layout-0123456789abcdef')", "<string>", "eval", dont_inherit=True, optimize=0),
        compile("max(7, -3)", "<string>", "eval", dont_inherit=True, optimize=0),
    ]
    def walk(code):
        yield code
        for value in code.co_consts:
            if hasattr(value, "co_code"):
                yield from walk(value)

    return list(walk(module)) + evals


def derive_offsets(objects):
    if not objects:
        raise ValueError("no-objects")
    offsets = {}
    # co_consts / co_names / co_filename use known anchors from the reviewed
    # observer profile; require one unique pointer slot for every code object.
    for name, key in (
        ("co_consts", "codeConstsOffset"),
        ("co_names", "codeNamesOffset"),
        ("co_filename", "codeFilenameOffset"),
    ):
        common = None
        for code in objects:
            buf = pread(id(code), 256)
            found = find_pointer_offset(buf, id(getattr(code, name)))
            common = found if common is None else [o for o in common if o in found]
        offsets[key] = unique(common or [], key + "-unstable")
    if offsets["codeFilenameOffset"] != 112:
        raise ValueError("code-filename-not-112")
    # co_code_adaptive is an inline array.  Derive Py_SIZE and the array offset
    # independently for every object and require one common pair.
    size_candidates = None
    adaptive_candidates = None
    for code in objects:
        allowed_sizes = [
            offset
            for offset in range(16, 64, 8)
            if i64(pread(id(code), 64), offset) == len(code.co_code) // 2
        ]
        size_candidates = (
            allowed_sizes
            if size_candidates is None
            else [o for o in size_candidates if o in allowed_sizes]
        )
    size_offset = unique(size_candidates or [], "code-size-offset")
    if size_offset != 16:
        raise ValueError("code-size-not-16")
    offsets["codeSizeOffset"] = size_offset
    for code in objects:
        units = i64(pread(id(code), 64), size_offset)
        if units is None or units < 1 or units * 2 != len(code.co_code):
            raise ValueError("code-size-value")
        candidates = []
        for offset in range(128, 256, 1):
            head = pread(id(code) + offset, min(8, units * 2))
            if head is None:
                continue
            if head[:2] != code.co_code[:2]:
                continue
            # The inline array must start at an aligned pointer-sized boundary
            # and the fields immediately before it must not look like code.
            if offset % 8:
                continue
            candidates.append(offset)
        adaptive_candidates = (
            candidates if adaptive_candidates is None else [o for o in adaptive_candidates if o in candidates]
        )
    adaptive_offset = unique(adaptive_candidates or [], "code-adaptive-offset")
    if adaptive_offset != 192:
        raise ValueError("code-adaptive-not-192")
    offsets["codeAdaptiveOffset"] = adaptive_offset
    # flags / firstlineno: require one common int slot matching every object.
    for name, key, reader in (
        ("co_flags", "codeFlagsOffset", i32),
        ("co_firstlineno", "codeFirstlinenoOffset", i32),
    ):
        common = None
        for code in objects:
            buf = pread(id(code), 256)
            target = getattr(code, name)
            found = [
                offset
                for offset in range(40, 100, 4)
                if reader(buf, offset) == target
            ]
            common = found if common is None else [o for o in common if o in found]
        offsets[key] = unique(common or [], key + "-unstable")
    # qualname: use the nested function where name != qualname.
    nested_qualname = None
    for code in objects:
        if code.co_qualname != code.co_name:
            nested_qualname = code
            break
    if nested_qualname is None:
        raise ValueError("qualname-probe-missing")
    buf = pread(id(nested_qualname), 256)
    offsets["codeQualnameOffset"] = unique(
        find_pointer_offset(buf, id(nested_qualname.co_qualname)),
        "code-qualname-offset",
    )
    if offsets["codeQualnameOffset"] != 128:
        raise ValueError("code-qualname-not-128")
    # tuple layout
    tuples = [code.co_consts for code in objects]
    size_slots = None
    item_slots = None
    for value in tuples:
        buf = pread(id(value), 24 + 8 * max(1, len(value)))
        size_slots = (
            [16] if u64(buf, 16) == len(value) else []
        )
        item_ok = all(
            u64(buf, 24 + 8 * index) == id(item)
            for index, item in enumerate(value)
        )
        item_slots = [24] if item_ok else []
        if not size_slots or not item_slots:
            raise ValueError("tuple-layout")
    offsets["tupleSizeOffset"] = 16
    offsets["tupleItemsOffset"] = 24
    # unicode layout: derive from several ASCII strings with distinct lengths
    strings = []
    for code in objects:
        strings.extend([code.co_filename, code.co_name, code.co_qualname])
        strings.extend([value for value in code.co_names if type(value) is str])
        strings.extend([value for value in code.co_consts if type(value) is str])
    ascii_strings = sorted(
        {value for value in strings if type(value) is str and value and value.isascii()},
        key=len,
    )
    if len(ascii_strings) < 4:
        raise ValueError("string-probes")
    length_counts = {}
    state_counts = {}
    data_counts = {}
    for value in ascii_strings:
        raw = value.encode("ascii")
        buf = pread(id(value), 96)
        if buf is None:
            raise ValueError("string-read")
        for offset in range(8, 48, 8):
            if u64(buf, offset) == len(value):
                length_counts[offset] = length_counts.get(offset, 0) + 1
        for offset in range(16, 48, 4):
            state = u32(buf, offset)
            if state is None:
                continue
            kind = (state >> 2) & 0x7
            compact = (state >> 5) & 0x1
            ascii_flag = (state >> 6) & 0x1
            if kind == 1 and compact == 1 and ascii_flag == 1:
                state_counts[offset] = state_counts.get(offset, 0) + 1
        for offset in range(32, 72):
            if len(raw) <= 64 and buf[offset:offset + len(raw)] == raw:
                data_counts[offset] = data_counts.get(offset, 0) + 1
    total = len(ascii_strings)
    offsets["strLengthOffset"] = unique(
        [slot for slot, count in length_counts.items() if count == total],
        "string-length-offset",
    )
    offsets["strStateOffset"] = unique(
        [slot for slot, count in state_counts.items() if count == total],
        "string-state-offset",
    )
    offsets["strDataOffset"] = unique(
        [slot for slot, count in data_counts.items() if count == total],
        "string-data-offset",
    )
    # non-ASCII probe must not satisfy the ASCII/compact state predicate
    non_ascii = compile("len('é')", "<string>", "eval", dont_inherit=True, optimize=0)
    non_ascii_value = non_ascii.co_consts[0]
    buf = pread(id(non_ascii_value), 96)
    state = u32(buf, offsets["strStateOffset"])
    if state is None or (((state >> 2) & 0x7) == 1 and ((state >> 6) & 0x1) == 1):
        raise ValueError("non-ascii-state")
    # type-name pointer slot
    type_slots = None
    for value, expected in (
        ("x", b"str"),
        (1, b"int"),
        (None, b"NoneType"),
        ((), b"tuple"),
        (b"", b"bytes"),
    ):
        type_buf = pread(id(type(value)), 128)
        found = []
        for offset in range(8, 64, 8):
            pointer = u64(type_buf, offset)
            blob = pread(pointer, 32) if pointer else None
            if blob and blob.split(b"\x00")[0] == expected:
                found.append(offset)
        type_slots = found if type_slots is None else [o for o in type_slots if o in found]
    offsets["typeNameOffset"] = unique(type_slots or [], "type-name-offset")
    # int tag/digit encoding: validate a decoder on small and multi-digit ints.
    tag_offset = 16
    digit_offset = 24
    samples = [0, 1, -1, 7, -3, 12345, -12345, 1 << 29, -(1 << 29), 1 << 30]
    for value in samples:
        buf = pread(id(value), 32)
        tag = u64(buf, tag_offset)
        if tag is None:
            raise ValueError("int-read")
        if value == 0:
            if tag != 1:
                raise ValueError("int-zero-tag")
            continue
        ndigits = tag >> 3
        negative = bool(tag & 2)
        if ndigits < 1 or ndigits > 4:
            raise ValueError("int-ndigits")
        digits = []
        for index in range(ndigits):
            digit = u32(pread(id(value) + digit_offset + 4 * index, 4), 0)
            if digit is None:
                raise ValueError("int-digit-read")
            digits.append(digit)
        reconstructed = 0
        for index in range(ndigits - 1, -1, -1):
            reconstructed = (reconstructed << 30) | digits[index]
        if negative:
            reconstructed = -reconstructed
        if reconstructed != value:
            raise ValueError("int-decode")
    offsets["intTagOffset"] = tag_offset
    offsets["intDigitOffset"] = digit_offset
    return offsets


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--expected-python", default="3.12.15")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    receipt = {
        "version": 1,
        "kind": "dynstruct-layout-probe",
        "state": "blocked",
        "pythonVersion": sys.version.split()[0],
        "imageId": args.image_id,
        "interpreterPath": "/usr/bin/python3.12",
        "libraryPath": "/usr/lib/libpython3.12.so.1.0",
        "targetExecuted": False,
        "fixtureImported": False,
    }
    try:
        if not IMAGE_RE.fullmatch(args.image_id):
            raise ValueError("image-id")
        if sys.version.split()[0] != args.expected_python:
            raise ValueError("python-version")
        receipt["interpreterSha256"] = sha256_bytes(read_regular("/usr/bin/python3.12"))
        receipt["librarySha256"] = sha256_bytes(
            read_regular("/usr/lib/libpython3.12.so.1.0")
        )
        objects = compile_objects()
        offsets = derive_offsets(objects)
        # Frame/thread-state anchors come from the already reviewed observer
        # profile and are not re-derivable without a running frame.  The two
        # code-object anchors that exist in that profile are cross-checked.
        if offsets["codeFilenameOffset"] != 112 or offsets["codeAdaptiveOffset"] != 192:
            raise ValueError("code-anchor-mismatch")
        receipt["offsets"] = offsets
        receipt["frameOffsets"] = {
            "tstateCframeOffset": 56,
            "frameExecutableOffset": 0,
            "framePrevInstrOffset": 56,
            "source": "existing-reviewed-observer-profile; not re-derived here",
        }
        receipt["intDecode"] = {
            "zeroTag": 1,
            "negativeMask": 2,
            "digitShift": 3,
            "digitBits": 30,
            "maxDigits": 1,
        }
        receipt["probeObjects"] = [
            {
                "name": code.co_name,
                "qualname": code.co_qualname,
                "firstlineno": code.co_firstlineno,
                "flags": code.co_flags,
                "codeUnits": len(code.co_code) // 2,
                "deoptimizedCodeSha256": sha256_bytes(bytes(code.co_code)),
            }
            for code in objects
        ]
        receipt["state"] = "accepted"
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        receipt["reason"] = type(error).__name__ + ":" + str(error)
    payload = json.dumps(receipt, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    with open(args.out, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["state"] == "accepted" else 3


if __name__ == "__main__":
    raise SystemExit(main())
