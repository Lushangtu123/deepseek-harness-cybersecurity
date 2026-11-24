#!/usr/bin/env python3
"""Pinned-image pure compile/bind tool for the stdlib CLI revision experiment.

This tool only reads frozen source bytes, parses them with ``ast``, compiles
them with the pinned interpreter, inspects code objects, and compiles tool-owned
probe templates.  It never imports or executes a fixture, never starts a target
process, and never reads target output.

Two modes:

``bind``
    Compile every frozen fixture once, locate the frozen CALL selector, derive
    the source-derived ``pointId`` (old shape), the caller code-object
    descriptor (compile-time identity) and the new ``bindingId`` core.

``structure``
    Render one attempt payload from its frozen template and the fresh
    challenge, compile it as an eval program, and emit the expected structure
    fingerprint plus the tool-owned data-only baseline.  This is the trusted
    compile side of the B1 witness.  The target is not started here.

Both modes require the layout receipt produced by ``tools/layout_probe.py`` in
the same pinned image; offsets are never guessed in this tool.
"""
import argparse
import ast
import dis
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structure  # noqa: E402  (pure tool module)

MAX_SOURCE_BYTES = 1048576
RUNROOT = "/review/runroot"
IMAGE_RE = re.compile(r"sha256:[a-f0-9]{64}")
HASH_RE = re.compile(r"[a-f0-9]{64}")
CHALLENGE_RE = re.compile(r"[a-f0-9]{32}")
PROFILE = "stdlib-cli-v2-experiment"
BINDING_VERSION = 1
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"


def fail(reason):
    return {"state": "blocked", "reason": reason}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, limit=MAX_SOURCE_BYTES):
    if os.path.islink(path):
        raise ValueError("symlink")
    info = os.stat(path)
    if not os.path.isfile(path):
        raise ValueError("not-regular")
    if info.st_size <= 0 or info.st_size > limit:
        raise ValueError("size")
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) != info.st_size:
        raise ValueError("short-read")
    return data


def load_layout(path):
    data = read_regular(path, 65536)
    value = json.loads(data)
    if type(value) is not dict or value.get("state") != "accepted":
        raise ValueError("layout-state")
    offsets = value.get("offsets")
    if type(offsets) is not dict:
        raise ValueError("layout-offsets")
    required = {
        "codeSizeOffset",
        "codeAdaptiveOffset",
        "codeConstsOffset",
        "codeNamesOffset",
        "codeFilenameOffset",
        "codeFlagsOffset",
        "codeFirstlinenoOffset",
        "codeQualnameOffset",
        "tupleSizeOffset",
        "tupleItemsOffset",
        "strLengthOffset",
        "strStateOffset",
        "strDataOffset",
        "typeNameOffset",
        "intTagOffset",
        "intDigitOffset",
    }
    if set(offsets) != required:
        raise ValueError("layout-offset-keys")
    for key, offset in offsets.items():
        if type(offset) is not int or offset < 0 or offset > 4096:
            raise ValueError("layout-offset-value:" + key)
    return value, data


def line_starts(data):
    starts = [0]
    for index, value in enumerate(data):
        if value == 10:
            starts.append(index + 1)
    return starts


def position(starts, line, col):
    if type(line) is not int or type(col) is not int:
        raise ValueError("position-type")
    if line < 1 or line > len(starts) or col < 0:
        raise ValueError("position-range")
    return {"line": line, "col": col + 1, "offset": starts[line - 1] + col}


def span(starts, node):
    start = position(starts, node.lineno, node.col_offset)
    end = position(starts, node.end_lineno, node.end_col_offset)
    if end["offset"] <= start["offset"]:
        raise ValueError("empty-span")
    return {"start": start, "end": end}


def find_function(tree, name):
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(found) != 1:
        raise ValueError("function-selector-ambiguity")
    return found[0]


def find_call(function_node, callee):
    found = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == callee
                and len(child.args) >= 1
            ):
                found.append(child)
            walk(child)

    walk(function_node)
    if len(found) != 1:
        raise ValueError("call-selector-ambiguity")
    return found[0]


def enumerate_code(code):
    yield code
    for value in code.co_consts:
        if hasattr(value, "co_code"):
            yield from enumerate_code(value)


def match_positions(instruction, call_span):
    pos = instruction.positions
    if pos is None:
        return False
    return (
        pos.lineno == call_span["start"]["line"]
        and pos.col_offset == call_span["start"]["col"] - 1
        and pos.end_lineno == call_span["end"]["line"]
        and pos.end_col_offset == call_span["end"]["col"] - 1
    )


def locate_call(code, call_span, function_name):
    matches = []
    for code_object in enumerate_code(code):
        for instruction in dis.get_instructions(code_object):
            if instruction.opname == "CALL" and match_positions(instruction, call_span):
                matches.append((code_object, instruction.offset))
    if len(matches) != 1:
        raise ValueError("bytecode-call-ambiguity")
    code_object, offset = matches[0]
    if code_object.co_name != function_name:
        raise ValueError("bytecode-function-mismatch")
    if not code_object.co_filename.startswith(RUNROOT + "/"):
        raise ValueError("bytecode-filename")
    return code_object, offset


def compiler_identity(image_id):
    value = {
        "imageId": image_id,
        "pythonVersion": sys.version.split()[0],
        "interpreterPath": "/usr/bin/python3.12",
        "interpreterSha256": sha256_bytes(read_regular("/usr/bin/python3.12", 1 << 28)),
        "libraryPath": "/usr/lib/libpython3.12.so.1.0",
        "librarySha256": sha256_bytes(read_regular("/usr/lib/libpython3.12.so.1.0", 1 << 28)),
    }
    return value


def derive_one(entry, source_root, image_id, expected_python, layout, layout_sha):
    module_name = entry.get("module") or ""
    if not module_name or module_name.split(".")[0] in sys.stdlib_module_names:
        return fail("module-name")
    path = entry["path"]
    absolute = os.path.join(source_root, path)
    try:
        data = read_regular(absolute)
    except (OSError, ValueError) as error:
        return fail("fixture-read:" + str(error))
    source_sha = sha256_bytes(data)
    if entry.get("sourceSha256") != source_sha:
        return fail("fixture-digest-mismatch")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return fail("fixture-encoding")
    if data.startswith(b"\xef\xbb\xbf"):
        return fail("fixture-bom")
    try:
        tree = ast.parse(data, filename=path, mode="exec")
    except (SyntaxError, ValueError, RecursionError):
        return fail("fixture-parse")
    selector = entry.get("pointSelector") or {}
    if set(selector) != {"kind", "function", "callee"} or selector["kind"] != "call-in-function":
        return fail("selector-shape")
    if selector["callee"] != "eval":
        return fail("selector-callee-not-covered")
    try:
        function_node = find_function(tree, selector["function"])
        call_node = find_call(function_node, selector["callee"])
    except ValueError as error:
        return fail("selector:" + str(error))
    starts = line_starts(data)
    try:
        call_span = span(starts, call_node)
        argument_span = span(starts, call_node.args[0])
    except ValueError as error:
        return fail("span:" + str(error))
    point_core = {"sourceSha256": source_sha, "callee": "eval", "call": call_span}
    point = {
        "sourceSha256": source_sha,
        "callee": "eval",
        "call": call_span,
        "id": structure.digest(point_core),
        "builtinIdentity": "unverified",
        "argument": argument_span,
    }
    staged_name = os.path.basename(path)
    compile_filename = RUNROOT + "/" + staged_name
    try:
        code = compile(text, compile_filename, "exec", dont_inherit=True, optimize=0)
    except (SyntaxError, ValueError, RecursionError):
        return fail("fixture-compile")
    try:
        code_object, call_offset = locate_call(code, call_span, selector["function"])
    except ValueError as error:
        return fail("locate:" + str(error))
    if not isinstance(call_offset, int) or call_offset < 0 or call_offset > 1 << 20:
        return fail("call-offset-range")
    try:
        caller = structure.caller_descriptor(code_object)
    except structure.StructureUnsupported as error:
        return fail("caller-descriptor:" + str(error))
    caller_sha = structure.structure_digest(caller)
    # A runtime observation carries (qualname, firstlineno, flags, codeUnits,
    # constants, names).  That descriptor must be unique among all code objects
    # compiled from the same frozen bytes.
    collisions = 0
    for candidate in enumerate_code(code):
        try:
            descriptor = structure.caller_descriptor(candidate)
        except structure.StructureUnsupported:
            continue
        if structure.structure_digest(descriptor) == caller_sha:
            collisions += 1
    if collisions != 1:
        return fail("caller-identity-ambiguity")
    compiler = compiler_identity(image_id)
    if (
        not isinstance(compiler.get("imageId"), str)
        or not IMAGE_RE.fullmatch(compiler["imageId"])
        or compiler.get("pythonVersion") != expected_python
        or not HASH_RE.fullmatch(compiler.get("interpreterSha256") or "")
        or not HASH_RE.fullmatch(compiler.get("librarySha256") or "")
    ):
        return fail("compiler-identity-mismatch")
    # Every compiled caller descriptor of the fixture, so the judge can tell a
    # real event from an *observed unbound* function apart from a caller that
    # cannot be attributed at all.
    candidates = []
    for candidate in enumerate_code(code):
        try:
            descriptor = structure.caller_descriptor(candidate)
        except structure.StructureUnsupported:
            continue
        candidates.append({
            "qualname": descriptor["qualname"],
            "firstlineno": descriptor["firstlineno"],
            "callerSha256": structure.structure_digest(descriptor),
        })
    candidates.sort(key=lambda row: (row["firstlineno"], row["qualname"]))
    if not candidates:
        return fail("caller-candidates-empty")
    closure = {staged_name: source_sha}
    closure_sha = structure.digest(closure)
    code_object_identity = {
        "qualname": caller["qualname"],
        "firstlineno": caller["firstlineno"],
        "flags": caller["flags"],
        "codeUnits": caller["codeUnits"],
        "names": caller["names"],
        "consts": caller["consts"],
        "callerSha256": caller_sha,
        "deoptimizedCodeSha256": sha256_bytes(bytes(code_object.co_code)),
    }
    core = {
        "version": BINDING_VERSION,
        "profile": PROFILE,
        "path": staged_name,
        "pointId": point["id"],
        "closureSha256": closure_sha,
        "codeObject": code_object_identity,
        "callOffset": call_offset,
        "compiler": compiler,
    }
    binding_id = structure.digest(core)
    binding = dict(core)
    binding["bindingId"] = binding_id
    binding["bindingSha256"] = structure.digest(binding)
    return {
        "state": "accepted",
        "classId": entry["classId"],
        "fixture": path,
        "stagedPath": staged_name,
        "module": entry["module"],
        "callable": entry["callable"],
        "closure": closure,
        "closureSha256": closure_sha,
        "point": point,
        "selectorKind": selector["kind"],
        "callerDescriptor": caller,
        "callerSha256": caller_sha,
        "callerCandidates": candidates,
        "callOffset": call_offset,
        "codeObject": code_object_identity,
        "compiler": compiler,
        "bindingCore": core,
        "bindingId": binding_id,
        "binding": binding,
        "derivation": {
            "profile": PROFILE,
            "tool": "tools/experiment_compile.py",
            "toolSha256": sha256_bytes(read_regular(os.path.abspath(__file__))),
            "layoutSha256": layout_sha,
            "layoutStructureSha256": structure.digest(layout),
            "projectImported": False,
            "targetExecuted": False,
        },
    }


def render_payload(template, challenge):
    if type(template) is not str:
        raise ValueError("payload-template-type")
    if template.count("${challenge}") != 1 or "${" in template.replace("${challenge}", ""):
        raise ValueError("payload-template-placeholder")
    if not CHALLENGE_RE.fullmatch(challenge):
        raise ValueError("challenge-format")
    payload = template.replace("${challenge}", challenge)
    if len(payload.encode("utf-8")) > 1024:
        raise ValueError("payload-size")
    if any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in payload):
        raise ValueError("payload-non-printable")
    return payload


def structure_receipt(attempt, challenge, layout, layout_sha):
    role = attempt.get("payloadRole")
    if role not in {"computation", "data", "echo"}:
        return fail("payload-role")
    try:
        payload = render_payload(attempt["payloadTemplate"], challenge)
    except ValueError as error:
        return fail("payload-render:" + str(error))
    payload_sha = sha256_bytes(payload.encode("utf-8"))
    receipt = {
        "state": "prepared",
        "attempt": attempt["attempt"],
        "classId": attempt["classId"],
        "payloadRole": role,
        "challenge": challenge,
        "payload": payload,
        "payloadSha256": payload_sha,
        "payloadSyntax": None,
        "expectedComputation": None,
        "dataBaseline": None,
        "computationVsBaselineDistinct": None,
        "compiler": compiler_identity(IMAGE),
        "layoutSha256": layout_sha,
        "layoutStructureSha256": structure.digest(layout),
        "targetExecuted": False,
    }
    if role == "echo":
        # The echo fixture never compiles its payload as a dynamic program.
        receipt["payloadSyntax"] = "not-applicable"
    else:
        # For data rows the target compiles the *wrapped* value, not the raw
        # challenge; only that wrapped compile decides a syntax rejection.
        syntax_source = payload if role != "data" else structure.quoted_data_source(payload)
        try:
            compile(syntax_source, structure.DYNAMIC_FILENAME, "eval", dont_inherit=True, optimize=0)
            receipt["payloadSyntax"] = "valid"
        except SyntaxError:
            receipt["payloadSyntax"] = "syntax-error"
        except (ValueError, TypeError, MemoryError, RecursionError):
            # A null byte, a size guard or an unsupported structure is not a
            # syntax rejection and must never be labelled one.
            receipt["payloadSyntax"] = "other-error"
    if role == "echo":
        return receipt
    if role == "computation":
        expected, reason = structure.safe_structure_from_source(payload, layout)
        if expected is None:
            receipt.update(state="blocked", reason="computation-structure:" + str(reason))
            return receipt
        baseline, baseline_reason = structure.safe_structure_from_source(
            structure.quoted_data_source(payload), layout
        )
        receipt["expectedComputation"] = {
            "structure": expected,
            "structureSha256": structure.structure_digest(expected),
            "codeSha256": structure.code_digest_from_structure(expected),
        }
        receipt["dataBaseline"] = (
            {
                "structure": baseline,
                "structureSha256": structure.structure_digest(baseline),
                "codeSha256": structure.code_digest_from_structure(baseline),
            }
            if baseline is not None
            else None
        )
        receipt["dataBaselineReason"] = baseline_reason
        distinct = baseline is None or (
            structure.structure_digest(baseline) != structure.structure_digest(expected)
        )
        receipt["computationVsBaselineDistinct"] = distinct
        if not distinct:
            receipt.update(state="blocked", reason="computation-equals-data-baseline")
        return receipt
    baseline, reason = structure.safe_structure_from_source(
        structure.quoted_data_source(payload), layout
    )
    if baseline is None:
        receipt["dataBaseline"] = None
        receipt["dataBaselineReason"] = reason
        receipt["syntaxRejectExpected"] = reason == "syntax:SyntaxError"
        return receipt
    receipt["dataBaseline"] = {
        "structure": baseline,
        "structureSha256": structure.structure_digest(baseline),
        "codeSha256": structure.code_digest_from_structure(baseline),
    }
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["bind", "structure"])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--expected-python", default="3.12.15")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--challenge")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        plan_bytes = read_regular(args.plan)
        plan = json.loads(plan_bytes)
        layout, layout_raw = load_layout(args.layout)
        layout_sha = sha256_bytes(layout_raw)
    except (OSError, ValueError, UnicodeDecodeError) as error:
        print(json.dumps({"state": "blocked", "reason": "input-read:" + str(error)}))
        return 2
    if args.mode == "bind":
        results = []
        for entry in plan.get("fixtures", []):
            result = derive_one(
                entry, args.workspace, args.image_id, args.expected_python, layout, layout_sha
            )
            results.append(result)
            if result.get("state") != "accepted":
                break
        receipt = {
            "state": "accepted"
            if results and all(r.get("state") == "accepted" for r in results)
            else "blocked",
            "mode": "bind",
            "profile": PROFILE,
            "planSha256": sha256_bytes(plan_bytes),
            "layoutSha256": layout_sha,
            "layoutStructureSha256": structure.digest(layout),
            "imageId": args.image_id,
            "pythonVersion": sys.version.split()[0],
            "results": results,
            "targetExecuted": False,
            "fixtureImported": False,
        }
    else:
        if args.attempt is None or not args.challenge:
            print(json.dumps({"state": "blocked", "reason": "attempt-or-challenge-missing"}))
            return 2
        attempts = {a["attempt"]: a for a in plan.get("attempts", [])}
        attempt = attempts.get(args.attempt)
        if attempt is None:
            receipt = fail("attempt-not-in-plan")
        else:
            receipt = structure_receipt(attempt, args.challenge, layout, layout_sha)
            receipt["planSha256"] = sha256_bytes(plan_bytes)
    payload = json.dumps(receipt, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    with open(args.out, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt.get("state") in {"accepted", "prepared"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
