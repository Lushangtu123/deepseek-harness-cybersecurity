#!/usr/bin/env python3
"""Deterministic renderer for the frozen observer template.

The runner, the zero-target preflight and the judge all render through this one
function.  The judge uses it to rebuild the observer bytes from the frozen
template and the *verified* layout bytes and compares the result exactly with
the stored ``observer.bt``.  A changed layout, a changed template or a changed
runtime identity therefore cannot be hidden behind a passing receipt boolean.
"""
import hashlib
import re

PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")
FIELDS = {
    "codeConstsOffset",
    "codeNamesOffset",
    "codeFilenameOffset",
    "codeFlagsOffset",
    "codeFirstlinenoOffset",
    "codeQualnameOffset",
    "codeSizeOffset",
    "codeAdaptiveOffset",
    "tupleSizeOffset",
    "tupleItemsOffset",
    "strLengthOffset",
    "strStateOffset",
    "strDataOffset",
    "typeNameOffset",
    "intTagOffset",
    "intDigitOffset",
}
FRAME_FIELDS = {
    "tstateCframeOffset",
    "framePrevInstrOffset",
}


class RenderError(ValueError):
    pass


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _require_int(value, what):
    if type(value) is not int or value < 0 or value > 65536:
        raise RenderError("offset:" + what)
    return str(value)


def render(template_bytes, layout, layout_sha, profile_sha, run_id, tag, caller_path,
           call_offset, target_pid, target_uid, profile_name):
    """Return the exact rendered bytes for one verified attempt/preflight."""
    if type(template_bytes) is not bytes:
        raise RenderError("template-type")
    if type(layout) is not dict:
        raise RenderError("layout-type")
    offsets = layout.get("offsets")
    frame = layout.get("frameOffsets")
    if type(offsets) is not dict or set(offsets) != FIELDS:
        raise RenderError("layout-offsets")
    if type(frame) is not dict or not FRAME_FIELDS.issubset(frame):
        raise RenderError("layout-frame")
    if type(layout_sha) is not str or not re.fullmatch(r"[a-f0-9]{64}", layout_sha):
        raise RenderError("layout-sha")
    if type(profile_sha) is not str or not re.fullmatch(r"[a-f0-9]{64}", profile_sha):
        raise RenderError("profile-sha")
    for value, what in (
        (run_id, "run"),
        (tag, "tag"),
        (caller_path, "caller"),
        (profile_name, "profile"),
    ):
        if type(value) is not str or not value or "\n" in value or "\r" in value:
            raise RenderError(what)
    if type(target_pid) is not int or target_pid <= 0:
        raise RenderError("pid")
    if type(target_uid) is not int or target_uid < 0:
        raise RenderError("uid")
    replacements = {
        "__RUN_ID__": run_id,
        "__TAG__": tag,
        "__LAYOUT_SHA__": layout_sha,
        "__PROFILE_SHA__": profile_sha,
        "__TARGET_UID__": str(target_uid),
        "__MAX_EVENTS__": "4",
        "__MAX_DYN_UNITS__": "32",
        "__MAX_DYN_BYTES__": "64",
        "__MAX_STR__": "64",
        "__MAX_CONSTS__": "8",
        "__MAX_NAMES__": "16",
        "__MAX_CALLER_UNITS__": "512",
        "__PATH_MAX__": "128",
        "__CALLER_PATH__": caller_path,
        "__CALL_OFFSET__": _require_int(call_offset, "call"),
        "__CODE_CONSTS__": _require_int(offsets["codeConstsOffset"], "consts"),
        "__CODE_NAMES__": _require_int(offsets["codeNamesOffset"], "names"),
        "__CODE_FILENAME__": _require_int(offsets["codeFilenameOffset"], "filename"),
        "__CODE_FLAGS__": _require_int(offsets["codeFlagsOffset"], "flags"),
        "__CODE_FIRSTLINENO__": _require_int(offsets["codeFirstlinenoOffset"], "firstlineno"),
        "__CODE_QUALNAME__": _require_int(offsets["codeQualnameOffset"], "qualname"),
        "__CODE_SIZE__": _require_int(offsets["codeSizeOffset"], "size"),
        "__CODE_ADAPTIVE__": _require_int(offsets["codeAdaptiveOffset"], "adaptive"),
        "__TUPLE_SIZE__": _require_int(offsets["tupleSizeOffset"], "tuple-size"),
        "__TUPLE_ITEMS__": _require_int(offsets["tupleItemsOffset"], "tuple-items"),
        "__STR_LENGTH__": _require_int(offsets["strLengthOffset"], "str-length"),
        "__STR_STATE__": _require_int(offsets["strStateOffset"], "str-state"),
        "__STR_DATA__": _require_int(offsets["strDataOffset"], "str-data"),
        "__TYPE_NAME__": _require_int(offsets["typeNameOffset"], "type-name"),
        "__INT_TAG__": _require_int(offsets["intTagOffset"], "int-tag"),
        "__INT_DIGIT__": _require_int(offsets["intDigitOffset"], "int-digit"),
        "__TSTATE_CFRAME__": _require_int(frame["tstateCframeOffset"], "tstate"),
        "__FRAME_PREV_INSTR__": _require_int(frame["framePrevInstrOffset"], "prev-instr"),
        "__TARGET_PID__": str(target_pid),
    }
    try:
        text = template_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise RenderError("template-encoding") from None
    for key, value in replacements.items():
        if key not in text:
            raise RenderError("template-placeholder-missing:" + key)
        text = text.replace(key, value)
    leftover = PLACEHOLDER_RE.search(text)
    if leftover:
        raise RenderError("template-placeholder-unresolved:" + leftover.group(0))
    return text.encode("utf-8")
