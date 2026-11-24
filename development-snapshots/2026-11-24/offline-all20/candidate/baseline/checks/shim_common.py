#!/usr/bin/env python3
"""Recorded shim helpers for the offline controller tests.

Nothing here executes a fixture.  The Docker shim reproduces the *pure* compile
and layout tools by calling their real functions with a simulated runtime
identity; the target and observer are recorded scenarios.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def state_dir():
    return Path(os.environ["SCE_SHIM_STATE"])


def root_dir():
    return Path(os.environ["SCE_ROOT"])


def tools_dir():
    return root_dir() / "tools"


def profile_lock():
    path = root_dir() / "tools" / "observer-profile.lock.json"
    return json.loads(path.read_text()), sha_file(path)


def fake_runtime():
    """Recorded runtime identity copied from the sealed observer profile.

    The shim never claims a real image identity: it reproduces the exact values
    of the frozen profile lock so simulated receipts exercise the same exact
    comparison the real pinned image will use.
    """
    profile, _ = profile_lock()
    return {
        "imageId": profile["imageId"],
        "pythonVersion": profile["pythonVersion"],
        "interpreterPath": profile["interpreterPath"],
        "interpreterSha256": profile["interpreterSha256"],
        "libraryPath": profile["libraryPath"],
        "librarySha256": profile["librarySha256"],
    }


def translate(container, path):
    for mount in container.get("mounts") or []:
        source = mount.get("Source")
        destination = mount.get("Destination")
        if destination and path == destination:
            return Path(source)
        if destination and path.startswith(destination.rstrip("/") + "/"):
            return Path(source) / path[len(destination.rstrip("/")) + 1:]
    raise FileNotFoundError(path)


def load_container(identifier):
    directory = state_dir() / "containers"
    directory.mkdir(parents=True, exist_ok=True)
    candidates = []
    for path in directory.glob("*.json"):
        value = json.loads(path.read_text())
        if value.get("removed"):
            continue
        if value["id"] == identifier or value["id"].startswith(identifier) or value["name"] == identifier:
            candidates.append(value)
    if len(candidates) != 1:
        return None
    return candidates[0]


def save_container(container):
    directory = state_dir() / "containers"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (container["id"] + ".json")).write_text(json.dumps(container, sort_keys=True, indent=1))


def container_json(container):
    host = {
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "Memory": 512 * 1024 * 1024,
        "MemorySwap": 512 * 1024 * 1024,
        "NanoCpus": 1000000000,
        "PidsLimit": 64,
        "Tmpfs": {"/tmp": "rw,size=32m,nosuid,nodev,noexec"},
    }
    mounts = [{"Type": "tmpfs", "Source": "", "Destination": "/tmp", "RW": True}]
    for mount in container.get("mounts") or []:
        mounts.append({
            "Type": "bind",
            "Source": mount["Source"],
            "Destination": mount["Destination"],
            "RW": False,
        })
    return {
        "Id": container["id"],
        "Name": "/" + container["name"],
        "Config": {
            "Image": container["image"],
            "User": "65534:65534",
            "Entrypoint": [container["entrypoint"]],
            "Labels": container.get("labels") or {},
        },
        "State": {"Status": container.get("status", "created"), "Pid": container.get("pid") or 0},
        "Mounts": mounts,
        "HostConfig": host,
    }


def layout_receipt():
    sys.path.insert(0, str(tools_dir()))
    import layout_probe
    objects = layout_probe.compile_objects()
    offsets = layout_probe.derive_offsets(objects)
    runtime = fake_runtime()
    return {
        "version": 1,
        "kind": "dynstruct-layout-probe",
        "state": "accepted",
        "pythonVersion": runtime["pythonVersion"],
        "imageId": IMAGE,
        "interpreterPath": runtime["interpreterPath"],
        "libraryPath": runtime["libraryPath"],
        "targetExecuted": False,
        "fixtureImported": False,
        "interpreterSha256": runtime["interpreterSha256"],
        "librarySha256": runtime["librarySha256"],
        "offsets": offsets,
        "frameOffsets": {
            "tstateCframeOffset": 56,
            "frameExecutableOffset": 0,
            "framePrevInstrOffset": 56,
            "source": "recorded-shim",
        },
        "intDecode": {"zeroTag": 1, "negativeMask": 2, "digitShift": 3,
                      "digitBits": 30, "maxDigits": 1},
        "probeObjects": [
            {
                "name": code.co_name,
                "qualname": code.co_qualname,
                "firstlineno": code.co_firstlineno,
                "flags": code.co_flags,
                "codeUnits": len(code.co_code) // 2,
                "deoptimizedCodeSha256": sha_bytes(bytes(code.co_code)),
            }
            for code in objects
        ],
    }


def bind_receipt(container):
    sys.path.insert(0, str(tools_dir()))
    import experiment_compile as ec
    import structure
    plan_path = translate(container, "/review/input/experiment-plan.json")
    layout_path = translate(container, "/review/input/layout.json")
    workspace = translate(container, "/review/input/fixtures")
    plan_bytes = Path(plan_path).read_bytes()
    plan = json.loads(plan_bytes)
    layout = json.loads(Path(layout_path).read_bytes())
    runtime = fake_runtime()
    original_identity = ec.compiler_identity
    original_read = ec.read_regular

    def identity(image_id):
        return dict(runtime)

    def read_regular(path, limit=ec.MAX_SOURCE_BYTES):
        if path == "/usr/lib/libpython3.12.so.1.0":
            return (state_dir() / "libpython3.12.so.1.0").read_bytes()
        return original_read(path, limit)

    ec.compiler_identity = identity
    ec.read_regular = read_regular
    try:
        results = []
        layout_sha = sha_bytes(Path(layout_path).read_bytes())
        for entry in plan.get("fixtures", []):
            result = ec.derive_one(entry, str(workspace), IMAGE, "3.12.15", layout, layout_sha)
            results.append(result)
            if result.get("state") != "accepted":
                break
    finally:
        ec.compiler_identity = original_identity
        ec.read_regular = original_read
    return {
        "state": "accepted" if results and all(r.get("state") == "accepted" for r in results) else "blocked",
        "mode": "bind",
        "profile": "stdlib-cli-v2-experiment",
        "planSha256": sha_bytes(plan_bytes),
        "layoutSha256": sha_bytes(Path(layout_path).read_bytes()),
        "layoutStructureSha256": structure.digest(layout),
        "imageId": IMAGE,
        "pythonVersion": "3.12.15",
        "results": results,
        "targetExecuted": False,
        "fixtureImported": False,
    }


def structure_receipt(container, attempt_number, challenge):
    sys.path.insert(0, str(tools_dir()))
    import experiment_compile as ec
    plan_path = translate(container, "/review/input/experiment-plan.json")
    layout_path = translate(container, "/review/input/layout.json")
    plan_bytes = Path(plan_path).read_bytes()
    plan = json.loads(plan_bytes)
    layout = json.loads(Path(layout_path).read_bytes())
    original_read = ec.read_regular

    def read_regular(path, limit=ec.MAX_SOURCE_BYTES):
        if path == "/usr/lib/libpython3.12.so.1.0":
            return (state_dir() / "libpython3.12.so.1.0").read_bytes()
        return original_read(path, limit)

    original_identity = ec.compiler_identity

    def identity(image_id):
        return dict(fake_runtime())

    ec.read_regular = read_regular
    ec.compiler_identity = identity
    try:
        attempt = next(item for item in plan["attempts"] if item["attempt"] == attempt_number)
        layout_sha = sha_bytes(Path(layout_path).read_bytes())
        receipt = ec.structure_receipt(attempt, challenge, layout, layout_sha)
        receipt["planSha256"] = sha_bytes(plan_bytes)
    finally:
        ec.read_regular = original_read
        ec.compiler_identity = original_identity
    return receipt


def preflight_config(container=None):
    sys.path.insert(0, str(tools_dir()))
    import preflight_selfcheck as sc
    import structure
    profile, profile_sha = profile_lock()
    layout = {
        "offsets": __import__("layout_probe").derive_offsets(__import__("layout_probe").compile_objects()),
        "frameOffsets": {"tstateCframeOffset": 56, "frameExecutableOffset": 0,
                         "framePrevInstrOffset": 56},
    }
    source_path = tools_dir() / "preflight_selfcheck.py"
    source = source_path.read_text()
    offset, code = sc.find_call_offset(source, sc.SELF_PATH)
    expected = structure.structure_from_source("0", layout)
    runtime = fake_runtime()
    command = (container or {}).get("command") or []
    preflight_id = "preflight"
    if "--preflight-id" in command:
        preflight_id = command[command.index("--preflight-id") + 1]
    return {
        "kind": "zero-target-preflight-config",
        "protocolRevision": 3,
        "preflightId": preflight_id,
        "callerPath": sc.SELF_PATH,
        "sourceSha256": sha_file(source_path),
        "callOffset": offset,
        "callerDescriptor": structure.caller_descriptor(code),
        "callerSha256": structure.structure_digest(structure.caller_descriptor(code)),
        "layout": layout,
        "expectedStructure": expected,
        "expectedStructureSha256": structure.structure_digest(expected),
        "expectedCodeSha256": structure.code_digest_from_structure(expected),
        "intZeroTag": 1,
        "profileSha256": profile_sha,
        "profile": {
            "imageId": profile["imageId"],
            "pythonVersion": profile["pythonVersion"],
            "interpreterPath": profile["interpreterPath"],
            "libraryPath": profile["libraryPath"],
            "interpreterSha256": profile["interpreterSha256"],
            "librarySha256": profile["librarySha256"],
            "bpftraceVersion": profile["bpftraceVersion"],
            "mechanism": profile["mechanism"],
        },
        "pythonVersion": runtime["pythonVersion"],
        "interpreterSha256": runtime["interpreterSha256"],
        "librarySha256": runtime["librarySha256"],
    }


def _const_lines(prefix, consts):
    lines = []
    for index, item in enumerate(consts):
        kind = item.get("t")
        if kind == "none":
            lines.append("%s %d n" % (prefix, index))
        elif kind == "int":
            value = item["v"]
            neg = 2 if value < 0 else 0
            lines.append("%s %d i %d %d" % (prefix, index, neg, abs(value)))
        elif kind == "str":
            raw = item["v"].encode("ascii")
            lines.append("%s %d s %d" % (prefix, index, len(raw)))
            lines.extend("%sW %d %d %x" % (prefix, index, j, byte)
                         for j, byte in enumerate(raw))
        else:
            raise ValueError("unsupported-const:" + str(kind))
    return lines


def _name_lines(prefix, names):
    lines = []
    for index, item in enumerate(names):
        raw = item["v"].encode("ascii")
        lines.append("%s %d %d" % (prefix, index, len(raw)))
        lines.extend("%sW %d %d %x" % (prefix, index, j, byte)
                     for j, byte in enumerate(raw))
    return lines


def format_rh(payload):
    """Independent `%rh` wire formatter: lower-case pairs joined by one space.

    This deliberately does not import either parser.  It mirrors the pinned
    upstream ``hex_format_buffer`` with ``keep_ascii=false`` and
    ``escape_hex=false``: a space is emitted between bytes, never after the
    last byte.  An empty payload is represented by the record-level ``-``.
    """
    return " ".join("%02x" % byte for byte in payload)


def _buffer_token(payload, protocol):
    if not payload:
        return "-"
    if protocol == "buffer-v2":
        return format_rh(payload)
    if protocol == "buffer-v1":
        return payload.hex()
    raise ValueError("unknown-buffer-protocol:" + str(protocol))


def _buffer_record(prefix, payload, index=None, protocol="buffer-v1"):
    token = _buffer_token(payload, protocol)
    if index is None:
        return "%s %d %s" % (prefix, len(payload), token)
    return "%s %d %d %s" % (prefix, index, len(payload), token)


def _buffer_const_lines(prefix, consts, protocol):
    lines = ["%sN %d" % (prefix, len(consts))]
    for index, item in enumerate(consts):
        kind = item.get("t")
        if kind == "none":
            lines.append("%s %d n" % (prefix, index))
        elif kind == "int":
            value = item["v"]
            neg = 2 if value < 0 else 0
            lines.append("%s %d i %d %d" % (prefix, index, neg, abs(value)))
        elif kind == "str":
            lines.append(_buffer_record(prefix + "B", item["v"].encode("ascii"),
                                        index, protocol=protocol))
        else:
            raise ValueError("unsupported-const:" + str(kind))
    return lines


def _buffer_name_lines(prefix, names, protocol):
    lines = ["%sN %d" % (prefix, len(names))]
    for index, item in enumerate(names):
        lines.append(_buffer_record(prefix + "B", item["v"].encode("ascii"),
                                    index, protocol=protocol))
    return lines


def event_lines(dynamic, caller, call_offset, protocol="legacy"):
    """Return recorded event lines for the selected explicit protocol."""
    code = bytes.fromhex(dynamic["codeHex"])
    lines = ["EVENT %d %d %d %d %d %d %d" % (
        dynamic["firstlineno"], dynamic["flags"], dynamic["codeBytes"] // 2,
        caller["firstlineno"], caller["flags"], caller["codeUnits"], call_offset,
    )]
    if protocol in ("buffer-v1", "buffer-v2"):
        lines.extend("DCODE %d %x" % (index, byte) for index, byte in enumerate(code))
        lines.extend(_buffer_const_lines("DCONST", dynamic["consts"], protocol))
        lines.extend(_buffer_name_lines("DNAME", dynamic["names"], protocol))
        lines.append(_buffer_record("QUALB", caller["qualname"].encode("ascii"),
                                    protocol=protocol))
        lines.extend(_buffer_const_lines("KCONST", caller["consts"], protocol))
        lines.extend(_buffer_name_lines("KNAME", caller["names"], protocol))
        return lines
    if protocol != "legacy":
        raise ValueError("unknown-observation-protocol:" + str(protocol))
    lines.extend("DCODE %d %x" % (index, byte) for index, byte in enumerate(code))
    lines.extend(_const_lines("DCONST", dynamic["consts"]))
    lines.extend(_name_lines("DNAME", dynamic["names"]))
    raw = caller["qualname"].encode("ascii")
    lines.append("QUAL %d" % len(raw))
    lines.extend("QUALW %d %x" % (index, byte) for index, byte in enumerate(raw))
    lines.extend(_const_lines("KCONST", caller["consts"]))
    lines.extend(_name_lines("KNAME", caller["names"]))
    return lines
