#!/usr/bin/env python3
"""Fail-closed judge for the structural probe experiment (admission revision).

Inputs: the binding receipt, the trusted expected-structure receipt, the collector
observation, the raw observer stream, the rendered observer template, the attempt
record and the host admission.

Order of work:

1. recompute every digest that can be recomputed and bind the raw observer bytes,
   the rendered template, the binding receipt, the expected receipt, the
   observation and the attempt record together (any break is ``unknown``);
2. verify the identity receipts: pinned image, interpreter and library digests
   agree between the binding and the expected compile, and the rendered template
   filters the recorded target pid/uid and the bound caller path/offset;
3. derive the verdict **from the observed events first** (event count, caller
   attribution, dynamic structure);
4. only then compare the derived verdict with the frozen event count, exit status
   and reason.  Any disagreement, missing capture, truncation, unsupported
   structure or unverifiable attribution stays ``unknown``.

It never reads target stdout/stderr and never trusts a target self-report.
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import buffer_protocol_v2  # noqa: E402
import observation_pure  # noqa: E402
import observer_render  # noqa: E402
import preflight_verify  # noqa: E402
import structure  # noqa: E402

HASH_RE = re.compile(r"[a-f0-9]{64}")
IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
PYTHON_VERSION = "3.12.15"
PROFILE = "stdlib-cli-v2-experiment"
TARGET_UID = 65534
OBSERVATION_PROTOCOL = buffer_protocol_v2.PROTOCOL
FRAMING_POLICY = buffer_protocol_v2.FRAMING_POLICY
BUFFER_PARSER_NAME = preflight_verify.BUFFER_PARSER_NAME
BUFFER_TEMPLATE_NAME = preflight_verify.BUFFER_TEMPLATE_NAME
EXCLUDED_REASONS = {"syntax-reject", "no-dynamic-event", "data-only-structure",
                    "caller-identity-mismatch"}
CANONICAL_OBSERVATION_FIELDS = (
    "version", "kind", "protocol", "framingPolicy", "runId", "tag",
    "targetPid", "targetUid", "rawSha256", "rawBytes", "callerPath",
    "callOffset", "state", "events", "errors", "targetExecuted",
    "targetSelfReportUsed", "rawTruncated", "trailingBlankLines", "marker",
    "markerCount", "beginCount", "endCount", "lineCount", "begin", "end",
    "endEvents", "trailingAfterEnd", "recordCounts",
)
WRAPPER_FIELDS = ("observerSha256", "observationSha256", "collector", "capture")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as handle:
        return sha256_bytes(handle.read())


def read_json(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    return json.loads(raw), sha256_bytes(raw)


def unknown(reason, **fields):
    return {"decision": "unknown", "reason": reason, **fields}


def strict_equal(left, right):
    """Equality that also rejects bool/int and other cross-type lookalikes."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if set(left) != set(right):
            return False
        return all(strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def compare_canonical(stored, recomputed):
    """Compare only canonical parser fields, never unrelated diagnostics."""
    if type(stored) is not dict:
        return "stored-observation-shape"
    for field in CANONICAL_OBSERVATION_FIELDS:
        if field not in stored:
            return "stored-missing:" + field
        if field not in recomputed:
            return "recomputed-missing:" + field
        if not strict_equal(stored[field], recomputed[field]):
            return "stored-mismatch:" + field
    return None


def verify_binding(receipt, class_id):
    if type(receipt) is not dict or receipt.get("state") != "accepted":
        return "binding-state", None
    if receipt.get("mode") != "bind" or receipt.get("targetExecuted") is not False:
        return "binding-mode", None
    if receipt.get("imageId") != IMAGE:
        return "binding-image", None
    results = receipt.get("results")
    if type(results) is not list or len(results) != 4:
        return "binding-results", None
    matched = [item for item in results if item.get("classId") == class_id]
    if len(matched) != 1:
        return "binding-class-selection", None
    result = matched[0]
    if type(result) is not dict or result.get("state") != "accepted":
        return "binding-result-state", None
    binding = result.get("binding")
    core = result.get("bindingCore")
    if type(binding) is not dict or type(core) is not dict:
        return "binding-shape", None
    if binding.get("bindingSha256") != structure.digest(
        {k: v for k, v in binding.items() if k != "bindingSha256"}
    ):
        return "binding-transport-digest", None
    if binding.get("bindingId") != structure.digest(core):
        return "binding-id", None
    if any(binding.get(key) != core.get(key) for key in core):
        return "binding-core", None
    if core.get("profile") != PROFILE or core.get("version") != 1:
        return "binding-profile", None
    if core.get("path") != result.get("stagedPath") or core.get("pointId") != result.get("point", {}).get("id"):
        return "binding-point-link", None
    compiler = core.get("compiler")
    if type(compiler) is not dict or set(compiler) != {
        "imageId",
        "pythonVersion",
        "interpreterPath",
        "interpreterSha256",
        "libraryPath",
        "librarySha256",
    }:
        return "binding-compiler", None
    if compiler.get("imageId") != IMAGE or compiler.get("pythonVersion") != PYTHON_VERSION:
        return "binding-compiler-image", None
    if not HASH_RE.fullmatch(compiler.get("interpreterSha256") or ""):
        return "binding-interpreter", None
    if not HASH_RE.fullmatch(compiler.get("librarySha256") or ""):
        return "binding-library", None
    closure = result.get("closure")
    if type(closure) is not dict or structure.digest(closure) != core.get("closureSha256"):
        return "binding-closure", None
    if result.get("closureSha256") != core.get("closureSha256"):
        return "binding-closure-link", None
    point = result.get("point")
    if type(point) is not dict or point.get("builtinIdentity") != "unverified":
        return "binding-point", None
    if point.get("id") != structure.digest(
        {key: point[key] for key in ("sourceSha256", "callee", "call")}
    ):
        return "binding-point-id", None
    if point.get("sourceSha256") not in closure.values():
        return "binding-source", None
    caller = result.get("callerDescriptor")
    if type(caller) is not dict or result.get("callerSha256") != structure.structure_digest(caller):
        return "binding-caller-digest", None
    if core.get("codeObject", {}).get("callerSha256") != result.get("callerSha256"):
        return "binding-caller-link", None
    if core.get("callOffset") != result.get("callOffset"):
        return "binding-offset-link", None
    if type(core.get("callOffset")) is not int or core["callOffset"] < 0:
        return "binding-offset", None
    return None, result


def caller_candidates(result):
    """Every compiled caller descriptor of the fixture, as recorded by bind."""
    rows = result.get("callerCandidates")
    if type(rows) is not list or not rows:
        return None
    out = []
    for row in rows:
        if type(row) is not dict or set(row) != {"qualname", "firstlineno", "callerSha256"}:
            return None
        if type(row["qualname"]) is not str or type(row["firstlineno"]) is not int:
            return None
        if not HASH_RE.fullmatch(row["callerSha256"] or ""):
            return None
        out.append(row)
    return out


def payload_syntax(payload, role):
    """Classify the source the target actually compiles.

    Data rows are interpolated into ``str("...")`` by the fixture, so the
    wrapped source is the one that can be a syntax rejection.  Echo rows never
    compile a payload.  Only a real ``SyntaxError`` is a syntax rejection; a
    ``ValueError`` from a null byte, a ``MemoryError`` or an unsupported
    structure is a different anomaly and must never be labelled one.
    """
    if role == "echo":
        return "not-applicable"
    source = payload if role != "data" else structure.quoted_data_source(payload)
    try:
        compile(source, structure.DYNAMIC_FILENAME, "eval", dont_inherit=True, optimize=0)
        return "valid"
    except SyntaxError:
        return "syntax-error"
    except (ValueError, TypeError, MemoryError, RecursionError):
        return "other-error"


def verify_expected(receipt):
    if type(receipt) is not dict or receipt.get("state") != "prepared":
        return "expected-state"
    if receipt.get("targetExecuted") is not False:
        return "expected-executed"
    if type(receipt.get("payloadRole")) is not str \
            or receipt.get("payloadRole") not in {"computation", "data", "echo"}:
        return "expected-role"
    payload = receipt.get("payload")
    if type(payload) is not str:
        return "expected-payload-type"
    if not isinstance(receipt.get("payloadSha256"), str) or not HASH_RE.fullmatch(receipt["payloadSha256"]):
        return "expected-payload-digest"
    if sha256_bytes(payload.encode("utf-8")) != receipt["payloadSha256"]:
        return "expected-payload-mismatch"
    actual_syntax = payload_syntax(payload, receipt["payloadRole"])
    if receipt.get("payloadSyntax") != actual_syntax:
        return "expected-payload-syntax-mismatch"
    reject_expected = receipt.get("syntaxRejectExpected")
    if reject_expected not in (None, True, False):
        return "expected-syntax-flag"
    if reject_expected is True:
        if receipt.get("payloadRole") != "data" or actual_syntax != "syntax-error":
            return "expected-syntax-flag-shape"
        if receipt.get("dataBaseline") is not None:
            return "expected-syntax-baseline"
    if receipt.get("payloadRole") == "data" and actual_syntax == "syntax-error" and reject_expected is not True:
        return "expected-syntax-flag-missing"
    expected = receipt.get("expectedComputation")
    if expected is not None:
        try:
            actual = structure.structure_digest(expected["structure"])
            code = structure.code_digest_from_structure(expected["structure"])
        except (KeyError, structure.StructureUnsupported, ValueError):
            return "expected-structure"
        if actual != expected.get("structureSha256") or code != expected.get("codeSha256"):
            return "expected-structure-digest"
    baseline = receipt.get("dataBaseline")
    if baseline is not None:
        try:
            actual = structure.structure_digest(baseline["structure"])
            code = structure.code_digest_from_structure(baseline["structure"])
        except (KeyError, structure.StructureUnsupported, ValueError):
            return "expected-baseline"
        if actual != baseline.get("structureSha256") or code != baseline.get("codeSha256"):
            return "expected-baseline-digest"
    if receipt.get("payloadRole") == "computation":
        if expected is None or receipt.get("computationVsBaselineDistinct") is not True:
            return "expected-computation"
    return None


def verify_observation(observation, caller_path, call_offset):
    if type(observation) is not dict or observation.get("state") != "complete":
        return "observation-state"
    if observation.get("targetSelfReportUsed") is not False:
        return "observation-self-report"
    if observation.get("callerPath") != caller_path or observation.get("callOffset") != call_offset:
        return "observation-filter"
    events = observation.get("events")
    if type(events) is not list:
        return "observation-events"
    for event in events:
        try:
            dynamic = structure.structure_digest(event["dynamicStructure"])
            caller = structure.structure_digest(event["callerDescriptor"])
        except (KeyError, structure.StructureUnsupported, ValueError):
            return "observation-structure"
        if dynamic != event.get("dynamicStructureSha256") or caller != event.get("callerSha256"):
            return "observation-digest"
    return None


def verify_rendered_template(text, attempt, result):
    """The rendered template must filter exactly the recorded target identity."""
    required = [
        "uprobe:/proc/%d/root/" % attempt["targetPid"],
        "if (pid != %d)" % attempt["targetPid"],
        "if (uid != %d)" % TARGET_UID,
        '!= "/review/runroot/%s"' % result["stagedPath"],
        "!= %d" % result["callOffset"],
        "run=%s tag=%s" % (attempt["runId"], attempt["challenge"][:12]),
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return "observer-template:" + ",".join(item[:24] for item in missing)
    if "__" in text:
        # An unresolved placeholder would change the observed filter at runtime.
        for token in ("__RUN_ID__", "__TAG__", "__TARGET_PID__", "__TARGET_UID__",
                      "__CALLER_PATH__", "__CALL_OFFSET__"):
            if token in text:
                return "observer-placeholder:" + token
    return None


def derive_verdict(events, result, expected, frozen, target_exit):
    """Derive the verdict from observed events only (no frozen comparison yet).

    Q4 is a syntax-rejection row: it is only ``excluded/syntax-reject`` when the
    frozen trusted compiler actually rejected the wrapped payload with a real
    ``SyntaxError``, the target really exited 3 and the observer captured a
    complete zero-event stream.  Every other zero-event trace is a normal
    ``no-dynamic-event``.  A structure mismatch, an unsupported structure or an
    unrelated exception can never become a syntax rejection.
    """
    count = len(events)
    syntax_candidate = (
        expected.get("payloadRole") == "data"
        and expected.get("payloadSyntax") == "syntax-error"
        and expected.get("syntaxRejectExpected") is True
        and expected.get("dataBaseline") is None
    )
    if count == 0 and syntax_candidate:
        if type(target_exit) is not int or target_exit != 3:
            return {"decision": "unknown", "reason": "syntax-reject-target-exit",
                    "observedEvents": 0, "targetExit": target_exit,
                    "syntaxReject": True}
        return {"decision": "excluded", "reason": "syntax-reject",
                "observedEvents": 0, "targetExit": target_exit,
                "syntaxReject": True}
    if count == 0:
        return {"decision": "excluded", "reason": "no-dynamic-event",
                "observedEvents": 0, "syntaxReject": False}
    if syntax_candidate:
        return {"decision": "unknown", "reason": "syntax-reject-with-events",
                "observedEvents": count, "syntaxReject": True}
    if count != 1:
        return {"decision": "unknown", "reason": "observed-event-count:%d" % count,
                "observedEvents": count, "syntaxReject": False}
    event = events[0]
    bound_caller = result["callerSha256"]
    candidates = caller_candidates(result)
    unbound = None
    if candidates is not None:
        unbound = next((row for row in candidates if row["callerSha256"] == event.get("callerSha256")), None)
    if event.get("callerSha256") == bound_caller:
        caller_state = "bound"
    elif candidates is None:
        return {"decision": "unknown", "reason": "caller-candidates-missing",
                "observedEvents": 1}
    elif unbound is not None:
        caller_state = "unbound:" + unbound["qualname"]
    else:
        return {"decision": "unknown", "reason": "caller-attribution-unverified",
                "observedEvents": 1, "observedCallerSha256": event.get("callerSha256")}
    structure_sha = event.get("dynamicStructureSha256")
    computation = expected.get("expectedComputation")
    baseline = expected.get("dataBaseline")
    if computation is not None and structure_sha == computation.get("structureSha256"):
        structure_state = "expected"
    elif baseline is not None and structure_sha == baseline.get("structureSha256"):
        structure_state = "data-only"
    elif computation is None:
        return {"decision": "unknown", "reason": "no-expected-computation",
                "observedEvents": 1, "callerState": caller_state}
    else:
        return {"decision": "unknown", "reason": "structure-mismatch",
                "observedEvents": 1, "callerState": caller_state,
                "observedStructureSha256": structure_sha,
                "expectedStructureSha256": computation.get("structureSha256"),
                "baselineStructureSha256": (baseline or {}).get("structureSha256")}
    if caller_state.startswith("unbound:"):
        return {"decision": "excluded", "reason": "caller-identity-mismatch",
                "observedEvents": 1, "callerState": caller_state,
                "unboundQualname": caller_state.split(":", 1)[1]}
    if structure_state == "data-only":
        return {"decision": "excluded", "reason": "data-only-structure",
                "observedEvents": 1, "callerState": caller_state}
    return {"decision": "confirmed", "reason": "structure-match",
            "observedEvents": 1, "callerState": caller_state,
            "observedStructureSha256": structure_sha,
            "observedCodeSha256": event.get("dynamicCodeSha256"),
            "expectedStructureSha256": computation.get("structureSha256"),
            "expectedCodeSha256": computation.get("codeSha256")}


def verify_governance(admission, manifest_path, preflight_path, review_path,
                      profile_path, layout_path, template_path, attempt, result):
    """Bind the formal verdict to the actual preflight evidence bundle."""
    root = os.path.dirname(os.path.abspath(manifest_path))
    relative = admission.get("preflightReceiptPath")
    if relative is None:
        return "preflight-path-missing", None
    try:
        receipt_path = preflight_verify.resolve_under(root, relative)
        bundle = preflight_verify.verify_preflight_evidence(
            root,
            receipt_path,
            os.path.join(root, "codex-review", "preflight-admission.json"),
            review_path,
            manifest_path,
            profile_path,
            expected_id=admission.get("preflightId"),
        )
    except preflight_verify.PreflightError as error:
        return "preflight:" + error.reason, None
    if admission.get("preflightReceiptSha256") != bundle["receiptSha256"]:
        return "preflight-tampered", bundle
    if admission.get("preflightId") != bundle["preflightId"]:
        return "preflight-id", bundle
    if bundle["receipt"].get("protocolManifestSha256") != sha256_file(manifest_path):
        return "preflight-manifest", bundle
    layout_sha = sha256_file(layout_path)
    if layout_sha != bundle["layoutSha256"]:
        return "layout-preflight-digest", bundle
    if layout_sha != attempt.get("layoutSha256"):
        return "layout-attempt-digest", bundle
    if structure.digest(bundle["layout"]) != attempt.get("layoutStructureSha256"):
        return "layout-attempt-structure", bundle
    template_sha = sha256_file(template_path)
    if bundle.get("bufferTemplateSha256") != template_sha:
        return "template-preflight-digest", bundle
    if bundle.get("frozenTemplateSha256") != template_sha:
        return "template-frozen-digest", bundle
    if template_sha != attempt.get("observerTemplateSha256"):
        return "template-attempt-digest", bundle
    if attempt.get("bufferTemplateSha256") != template_sha:
        return "template-attempt-buffer-digest", bundle
    if attempt.get("frozenTemplateSha256") != template_sha:
        return "template-attempt-frozen-digest", bundle
    parser_sha = sha256_file(os.path.join(root, "tools", BUFFER_PARSER_NAME))
    if bundle.get("bufferParserSha256") != parser_sha:
        return "parser-preflight-digest", bundle
    if attempt.get("bufferParserSha256") != parser_sha:
        return "parser-attempt-digest", bundle
    if attempt.get("observationProtocol") != OBSERVATION_PROTOCOL:
        return "attempt-observation-protocol", bundle
    if attempt.get("framingPolicy") != FRAMING_POLICY:
        return "attempt-framing-policy", bundle
    if result.get("derivation", {}).get("layoutSha256") != layout_sha:
        return "binding-layout-digest", bundle
    if result.get("derivation", {}).get("layoutStructureSha256") != structure.digest(bundle["layout"]):
        return "binding-layout-structure", bundle
    return None, bundle


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--review-receipt", required=True)
    parser.add_argument("--observer", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--observation-protocol", default=OBSERVATION_PROTOCOL)
    parser.add_argument("--framing-policy", default=FRAMING_POLICY)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    artifact = {
        "version": 3,
        "kind": "dynstruct-verification-artifact",
        "schema": "stdlib-cli-v2-experiment",
        "decision": "unknown",
        "reason": None,
        "reasons": [],
        "digestChecks": {},
        "identityChecks": {},
        "derived": None,
        "frozenExpectation": None,
        "targetOutcomeUsedAsEvidence": False,
        "targetStdoutUsedAsEvidence": False,
        "targetSelfReportUsedAsEvidence": False,
    }
    try:
        if args.observation_protocol != OBSERVATION_PROTOCOL:
            raise ValueError("observation-protocol:" + str(args.observation_protocol))
        if args.framing_policy != FRAMING_POLICY:
            raise ValueError("framing-policy:" + str(args.framing_policy))
        binding, binding_sha = read_json(args.binding)
        expected, expected_sha = read_json(args.expected)
        observation, observation_sha = read_json(args.observation)
        attempt, attempt_sha = read_json(args.attempt)
        admission, admission_sha = read_json(args.admission)
        manifest_sha = sha256_file(args.manifest)
        raw_bytes = preflight_verify.read_regular_bytes(args.raw, limit=1 << 22)
        raw_sha = sha256_bytes(raw_bytes)
        observer_sha = sha256_file(args.observer)
        layout_raw = preflight_verify.read_regular_bytes(args.layout)
        layout = json.loads(layout_raw)
        layout_sha = sha256_bytes(layout_raw)
        layout_structure_sha = structure.digest(layout)
        template_raw = preflight_verify.read_regular_bytes(args.template)
        template_sha = sha256_bytes(template_raw)
        try:
            profile, profile_sha = preflight_verify.load_profile(args.profile)
        except preflight_verify.PreflightError as error:
            raise ValueError("profile:" + error.reason) from None
        artifact.update(
            bindingSha256=binding_sha,
            expectedSha256=expected_sha,
            observationSha256=observation_sha,
            attemptSha256=attempt_sha,
            admissionSha256=admission_sha,
            protocolManifestSha256=manifest_sha,
            observerSha256=observer_sha,
            observationRawSha256=raw_sha,
            layoutSha256=layout_sha,
            layoutStructureSha256=layout_structure_sha,
            observerTemplateSha256=template_sha,
            profileSha256=profile_sha,
        )
        # ---- 1. digest chain: every artifact must be the one the runner recorded
        checks = {
            "attempt.bindingSha256 == binding bytes": attempt.get("bindingSha256") == binding_sha,
            "attempt.expectedSha256 == expected bytes": attempt.get("expectedSha256") == expected_sha,
            "attempt.observationSha256 == observation bytes": attempt.get("observationSha256") == observation_sha,
            "attempt.observationRawSha256 == raw observer bytes": attempt.get("observationRawSha256") == raw_sha,
            "observation.rawSha256 == raw observer bytes": observation.get("rawSha256") == raw_sha,
            "observation.rawBytes == raw size": observation.get("rawBytes") == len(raw_bytes),
            "observation.protocol == buffer-v2": observation.get("protocol") == OBSERVATION_PROTOCOL,
            "observation.framingPolicy == end-lf-padding-v1": observation.get("framingPolicy") == FRAMING_POLICY,
            "attempt.observationProtocol == buffer-v2": attempt.get("observationProtocol") == OBSERVATION_PROTOCOL,
            "attempt.framingPolicy == end-lf-padding-v1": attempt.get("framingPolicy") == FRAMING_POLICY,
            "attempt.bufferParserSha256 == actual parser bytes": attempt.get("bufferParserSha256") == sha256_file(os.path.join(os.path.dirname(os.path.abspath(args.manifest)), "tools", BUFFER_PARSER_NAME)),
            "attempt.observerSha256 == rendered template bytes": attempt.get("observerSha256") == observer_sha,
            "attempt.layoutSha256 == verified layout bytes": attempt.get("layoutSha256") == layout_sha,
            "attempt.layoutStructureSha256 == layout structure": attempt.get("layoutStructureSha256") == layout_structure_sha,
            "attempt.observerTemplateSha256 == frozen template bytes": attempt.get("observerTemplateSha256") == template_sha,
            "attempt.bufferTemplateSha256 == frozen template bytes": attempt.get("bufferTemplateSha256") == template_sha,
            "attempt.frozenTemplateSha256 == frozen template bytes": attempt.get("frozenTemplateSha256") == template_sha,
            "attempt.profileSha256 == sealed profile bytes": attempt.get("profileSha256") == profile_sha,
        }
        artifact["digestChecks"] = checks
        for name, ok in checks.items():
            if not ok:
                raise ValueError("digest-chain:" + name)

        if admission.get("state") != "approved":
            raise ValueError("admission-state")
        if admission.get("protocolRevision") != preflight_verify.PROTOCOL_REVISION:
            raise ValueError("admission-revision")
        if admission.get("protocolManifestSha256") != manifest_sha:
            raise ValueError("admission-manifest")
        number = attempt.get("attempt")
        if type(number) is not int or number not in admission.get("allowedAttempts", []):
            raise ValueError("admission-attempt")
        if attempt.get("challenge") != expected.get("challenge"):
            raise ValueError("challenge-mismatch")
        if attempt.get("planSha256") != expected.get("planSha256"):
            raise ValueError("attempt-plan-link")
        reason, result = verify_binding(binding, attempt.get("classId"))
        if reason:
            raise ValueError(reason)
        if result is None:
            raise ValueError("binding-result")
        if attempt.get("classId") != result.get("classId"):
            raise ValueError("attempt-class")
        if attempt.get("bindingId") != result.get("bindingId"):
            raise ValueError("attempt-binding-id")
        if attempt.get("pointId") != result.get("point", {}).get("id"):
            raise ValueError("attempt-point-id")
        if expected.get("attempt") != number or expected.get("classId") != attempt.get("classId"):
            raise ValueError("expected-attempt")
        if expected.get("planSha256") != attempt.get("planSha256"):
            raise ValueError("expected-plan-link")
        if expected.get("layoutSha256") != result.get("derivation", {}).get("layoutSha256"):
            raise ValueError("expected-layout-link")
        if expected.get("layoutSha256") != layout_sha:
            raise ValueError("expected-layout-bytes")
        if expected.get("layoutStructureSha256") != layout_structure_sha:
            raise ValueError("expected-layout-structure")
        reason, bundle = verify_governance(
            admission, args.manifest, args.preflight, args.review_receipt,
            args.profile, args.layout, args.template, attempt, result,
        )
        if reason:
            raise ValueError(reason)
        if bundle is None:
            raise ValueError("preflight-bundle")
        if template_raw != bundle.get("frozenTemplateBytes"):
            raise ValueError("template-not-frozen-v2")
        if layout_raw != bundle.get("layoutBytes"):
            raise ValueError("layout-not-verified-bytes")
        for field in ("observationProtocol", "framingPolicy",
                      "bufferParserSha256", "bufferTemplateSha256"):
            if field in admission and admission.get(field) != bundle.get(field):
                raise ValueError("admission-" + field)
        reason = verify_expected(expected)
        if reason:
            raise ValueError(reason)

        # ---- 2. identity receipts
        identity = {
            "profileSha256": profile_sha,
            "layoutSha256": layout_sha,
            "observerTemplateSha256": template_sha,
            "bindingImageId": result.get("compiler", {}).get("imageId"),
            "bindingPythonVersion": result.get("compiler", {}).get("pythonVersion"),
            "bindingInterpreterSha256": result.get("compiler", {}).get("interpreterSha256"),
            "expectedInterpreterSha256": expected.get("compiler", {}).get("interpreterSha256"),
            "bindingLibrarySha256": result.get("compiler", {}).get("librarySha256"),
            "expectedLibrarySha256": expected.get("compiler", {}).get("librarySha256"),
            "attemptTargetPid": attempt.get("targetPid"),
            "attemptTargetUid": attempt.get("targetUid"),
            "observationTargetPid": observation.get("targetPid"),
            "observationTargetUid": observation.get("targetUid"),
        }
        artifact["identityChecks"] = identity
        if identity["bindingImageId"] != IMAGE or identity["bindingPythonVersion"] != PYTHON_VERSION:
            raise ValueError("identity-image")
        if identity["bindingInterpreterSha256"] != identity["expectedInterpreterSha256"]:
            raise ValueError("identity-interpreter")
        if identity["bindingLibrarySha256"] != identity["expectedLibrarySha256"]:
            raise ValueError("identity-library")
        if identity["bindingInterpreterSha256"] != profile["interpreterSha256"]:
            raise ValueError("identity-profile-interpreter")
        if identity["bindingLibrarySha256"] != profile["librarySha256"]:
            raise ValueError("identity-profile-library")
        if type(identity["attemptTargetPid"]) is not int or identity["attemptTargetPid"] <= 0:
            raise ValueError("identity-target-pid")
        if identity["attemptTargetUid"] != TARGET_UID:
            raise ValueError("identity-target-uid")
        if identity["observationTargetPid"] != identity["attemptTargetPid"]:
            raise ValueError("identity-observation-pid")
        if identity["observationTargetUid"] != identity["attemptTargetUid"]:
            raise ValueError("identity-observation-uid")
        try:
            observer_raw = open(args.observer, "rb").read()
            template_text = observer_raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            raise ValueError("observer-template-unreadable") from None
        rebuilt = observer_render.render(
            template_raw, layout, layout_sha, profile_sha,
            attempt.get("runId"), attempt["challenge"][:12],
            "/review/runroot/" + result["stagedPath"], result["callOffset"],
            attempt.get("targetPid"), TARGET_UID, "stdlib-cli-v2-experiment",
        )
        if rebuilt != observer_raw:
            raise ValueError("observer-rebuild-mismatch")
        reason = verify_rendered_template(template_text, attempt, result)
        if reason:
            raise ValueError(reason)

        caller_path = "/review/runroot/" + result["stagedPath"]
        call_offset = result["callOffset"]
        if type(call_offset) is not int or call_offset < 0:
            raise ValueError("binding-call-offset")
        run_id = attempt.get("runId")
        challenge = attempt.get("challenge")
        if type(run_id) is not str or not run_id:
            raise ValueError("attempt-run-id")
        if type(challenge) is not str or not re.fullmatch(r"[a-f0-9]{32}", challenge):
            raise ValueError("attempt-challenge")
        tag = challenge[:12]
        # Independent recomputation from the full actual raw bytes.  Stored
        # events, stored hashes and any confirmed boolean are never evidence.
        observer_end = attempt.get("observerEnd") or {}
        recomputed = buffer_protocol_v2.parse_receipt(
            raw_bytes, run_id, tag, caller_path, call_offset,
            attempt.get("targetPid"), TARGET_UID,
            max_events=4, raw_truncated=observer_end.get("truncated") is True,
            require_events=None,
            forced_stop=(observer_end.get("forcedStop") is True
                         or observer_end.get("gracefulStop") is False),
            drain_incomplete=observer_end.get("drainComplete") is False,
            framing_policy=FRAMING_POLICY,
        )
        if recomputed.get("protocol") != OBSERVATION_PROTOCOL:
            raise ValueError("recomputed-observation-protocol")
        if recomputed.get("framingPolicy") != FRAMING_POLICY:
            raise ValueError("recomputed-framing-policy")
        if recomputed.get("state") != "complete":
            raise ValueError("recomputed-observation-state:" + ",".join(
                str(item) for item in (recomputed.get("errors") or [])))
        if recomputed.get("errors"):
            raise ValueError("recomputed-observation-errors")
        if recomputed.get("rawSha256") != raw_sha or recomputed.get("rawBytes") != len(raw_bytes):
            raise ValueError("recomputed-raw-identity")
        if recomputed.get("runId") != run_id or recomputed.get("tag") != tag:
            raise ValueError("recomputed-run-identity")
        if recomputed.get("callerPath") != caller_path or recomputed.get("callOffset") != call_offset:
            raise ValueError("recomputed-caller-filter")
        if recomputed.get("targetPid") != attempt.get("targetPid"):
            raise ValueError("recomputed-target-pid")
        if recomputed.get("targetUid") != attempt.get("targetUid"):
            raise ValueError("recomputed-target-uid")
        if recomputed.get("beginCount") != 1 or recomputed.get("endCount") != 1:
            raise ValueError("recomputed-markers")
        if recomputed.get("markerCount") != 1 or recomputed.get("marker") != buffer_protocol_v2.MARKER:
            raise ValueError("recomputed-buffer-marker")
        trailing = recomputed.get("trailingBlankLines")
        if type(trailing) is not int or not 0 <= trailing <= buffer_protocol_v2.MAX_TRAILING_BLANK_LINES:
            raise ValueError("recomputed-trailing-blank-lines")
        if recomputed.get("endEvents") != len(recomputed.get("events") or []):
            raise ValueError("recomputed-end-count")
        if recomputed.get("targetExecuted") is not False:
            raise ValueError("recomputed-target-executed")
        reason = verify_observation(recomputed, caller_path, call_offset)
        if reason:
            raise ValueError("recomputed-" + reason)
        reason = compare_canonical(observation, recomputed)
        if reason:
            raise ValueError("observation-canonical:" + reason)
        if observation.get("runId") != attempt.get("runId"):
            raise ValueError("observation-run")
        if "observerSha256" in observation and observation.get("observerSha256") != observer_sha:
            raise ValueError("observation-observer-digest")
        if "observationSha256" in observation and observation.get("observationSha256") != observation_sha:
            raise ValueError("observation-self-digest")
        if attempt.get("targetOutputDiagnosticOnly") is not True:
            raise ValueError("target-output-not-diagnostic")
        cleanup = attempt.get("cleanup") or {}
        if cleanup.get("confirmed") is not True:
            raise ValueError("cleanup-unconfirmed")

        # ---- 3. derive from the recomputed events, never from stored events
        frozen = attempt.get("expected") or {}
        target_exit = attempt.get("targetExit")
        if target_exit is not None and type(target_exit) is not int:
            artifact.update(
                decision="unknown",
                reason="invalid-returncode-type:" + type(target_exit).__name__,
                derived={"targetExit": target_exit},
            )
            raise SystemExit(3)
        derived = derive_verdict(recomputed["events"], result, expected,
                                frozen, target_exit)
        artifact["derived"] = derived
        artifact["frozenExpectation"] = frozen
        if derived["decision"] == "unknown":
            artifact.update(decision="unknown", reason=derived["reason"], derived=derived)
            raise SystemExit(3)
        if derived["observedEvents"] != frozen.get("dynamicEvents"):
            artifact.update(decision="unknown", reason="frozen-event-count-mismatch", derived=derived)
            raise SystemExit(3)
        if attempt.get("targetExit") != frozen.get("targetExit"):
            artifact.update(decision="unknown", reason="target-exit-mismatch", derived=derived)
            raise SystemExit(3)
        if frozen.get("decision") is not None and frozen["decision"] != derived["decision"]:
            artifact.update(decision="unknown", reason="frozen-decision-mismatch", derived=derived)
            raise SystemExit(3)
        if frozen.get("reason") is not None and frozen["reason"] != derived["reason"]:
            artifact.update(decision="unknown", reason="frozen-reason-mismatch", derived=derived)
            raise SystemExit(3)
        if derived["decision"] == "excluded":
            artifact.update(decision="excluded", reason=derived["reason"], derived=derived)
            if derived["reason"] not in EXCLUDED_REASONS:
                artifact.update(decision="unknown", reason="unclassified-exclusion")
                raise SystemExit(3)
            raise SystemExit(0)
        # confirmed
        event = recomputed["events"][0]
        artifact.update(
            decision="confirmed",
            reason="structure-match",
            derived=derived,
            bindingId=result["bindingId"],
            pointId=result["point"]["id"],
            callerSha256=result["callerSha256"],
            expectedStructureSha256=derived["expectedStructureSha256"],
            observedStructureSha256=event["dynamicStructureSha256"],
            expectedCodeSha256=derived["expectedCodeSha256"],
            observedCodeSha256=event["dynamicCodeSha256"],
            layoutSha256=layout_sha,
            layoutStructureSha256=layout_structure_sha,
            observerTemplateSha256=template_sha,
            profileSha256=profile_sha,
        )
    except SystemExit:
        pass
    except Exception as error:  # noqa: BLE001 - fail closed with a clear unknown
        artifact.update(decision="unknown",
                        reason=type(error).__name__ + ":" + str(error),
                        errorType=type(error).__name__)
    payload = json.dumps(artifact, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    with open(args.out, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"decision": artifact["decision"], "reason": artifact["reason"]}))
    return 0 if artifact["decision"] in {"confirmed", "excluded"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
