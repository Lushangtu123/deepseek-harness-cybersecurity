#!/usr/bin/env python3
"""Frozen zero-target self-check for the preflight container.

This is a *tool-owned* program.  It is not a fixture, is not in the blind-test
pool, and never imports or executes any experiment fixture or target.

Before GO it performs only static derivations:

* the pinned-image object layout and int-zero encoding via ``layout_probe``;
* the location of its own ``eval("0")`` CALL from a fresh compile;
* the expected structure of the literal ``"0"``.

It then prints one JSON configuration line and blocks for exactly one ``GO``
line.  After GO it evaluates the side-effect-free literal ``0`` once.  The
external observer, not this program, is the evidence source.
"""
import argparse
import ast
import ctypes
import dis
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import layout_probe  # noqa: E402
import structure  # noqa: E402

SELF_PATH = "/review/preflight/preflight_selfcheck.py"
PROFILE_PATH = "/review/preflight/observer-profile.lock.json"
GO_LINE = b"GO\n"


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


def find_call_offset(source, filename):
    """Locate the one CALL instruction for the literal ``eval("0")``."""
    tree = ast.parse(source, filename=filename, mode="exec")
    calls = []
    for node in ast.walk(tree):
        if type(node) is ast.Call and type(node.func) is ast.Name and node.func.id == "eval":
            calls.append(node)
    if len(calls) != 1:
        raise ValueError("selfcheck-call-count")
    call = calls[0]
    code = compile(source, filename, "exec", dont_inherit=True, optimize=0)
    matches = []
    for candidate in _walk(code):
        for instruction in dis.get_instructions(candidate):
            pos = instruction.positions
            if instruction.opname != "CALL" or pos is None:
                continue
            if (
                pos.lineno == call.lineno
                and pos.col_offset == call.col_offset
                and pos.end_lineno == call.end_lineno
                and pos.end_col_offset == call.end_col_offset
            ):
                matches.append((candidate, instruction.offset))
    if len(matches) != 1:
        raise ValueError("selfcheck-call-offset")
    candidate, offset = matches[0]
    if candidate.co_name != "_run":
        raise ValueError("selfcheck-call-function")
    return offset, candidate


def _walk(code):
    yield code
    for value in code.co_consts:
        if hasattr(value, "co_code"):
            yield from _walk(value)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-id", default="preflight")
    args = parser.parse_args(argv)
    source_path = os.path.abspath(__file__)
    source_bytes = read_regular(source_path)
    source = source_bytes.decode("utf-8")
    try:
        profile_bytes = read_regular(PROFILE_PATH)
        profile = json.loads(profile_bytes)
    except (OSError, ValueError, UnicodeDecodeError):
        sys.stderr.write("preflight-selfcheck: profile-unreadable\n")
        return 72
    layout = {
        "offsets": layout_probe.derive_offsets(layout_probe.compile_objects()),
        "frameOffsets": {
            "tstateCframeOffset": 56,
            "frameExecutableOffset": 0,
            "framePrevInstrOffset": 56,
        },
    }
    call_offset, caller_code = find_call_offset(source, SELF_PATH)
    caller_descriptor = structure.caller_descriptor(caller_code)
    expected = structure.structure_from_source("0", layout)
    zero_tag = int.from_bytes(
        ctypes.string_at(id(0) + layout["offsets"]["intTagOffset"], 8),
        "little",
    )
    interpreter_sha = sha256_bytes(read_regular("/usr/bin/python3.12"))
    library_sha = sha256_bytes(read_regular("/usr/lib/libpython3.12.so.1.0"))
    # The sealed profile fixes the *actual* runtime identity.  A shape-valid
    # but different digest is not accepted.
    if (profile.get("pythonVersion") != sys.version.split()[0]
            or profile.get("interpreterSha256") != interpreter_sha
            or profile.get("librarySha256") != library_sha
            or profile.get("imageId") != "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"):
        sys.stderr.write("preflight-selfcheck: profile-mismatch\n")
        return 72
    config = {
        "kind": "zero-target-preflight-config",
        "protocolRevision": 3,
        "preflightId": args.preflight_id,
        "callerPath": SELF_PATH,
        "sourceSha256": sha256_bytes(source_bytes),
        "callOffset": call_offset,
        "callerDescriptor": caller_descriptor,
        "callerSha256": structure.structure_digest(caller_descriptor),
        "layout": layout,
        "expectedStructure": expected,
        "expectedStructureSha256": structure.structure_digest(expected),
        "expectedCodeSha256": structure.code_digest_from_structure(expected),
        "intZeroTag": zero_tag,
        "profileSha256": sha256_bytes(profile_bytes),
        "profile": {
            "imageId": profile.get("imageId"),
            "pythonVersion": profile.get("pythonVersion"),
            "interpreterPath": profile.get("interpreterPath"),
            "libraryPath": profile.get("libraryPath"),
            "interpreterSha256": profile.get("interpreterSha256"),
            "librarySha256": profile.get("librarySha256"),
            "bpftraceVersion": profile.get("bpftraceVersion"),
            "mechanism": profile.get("mechanism"),
        },
        "pythonVersion": sys.version.split()[0],
        "interpreterSha256": interpreter_sha,
        "librarySha256": library_sha,
        "targetExecuted": False,
        "fixtureImported": False,
    }
    sys.stdout.write("PREFLIGHT-CONFIG " + json.dumps(config, sort_keys=True) + "\n")
    sys.stdout.flush()
    line = sys.stdin.buffer.readline(64)
    if line != GO_LINE:
        sys.stderr.write("preflight-selfcheck: go-handshake\n")
        return 70
    value = _run()
    return 0 if value == 0 else 1


def _run():
    #: The single observed dynamic call.  The literal is side-effect free.
    return eval("0")


if __name__ == "__main__":
    raise SystemExit(main())
