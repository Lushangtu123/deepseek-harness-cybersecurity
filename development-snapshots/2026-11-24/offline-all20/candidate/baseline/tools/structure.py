"""Canonical structure fingerprints for the stdlib CLI revision experiment.

This module is a *pure* tool module.  It never imports, compiles from disk as a
side effect, execs, or runs target code.  ``structure_from_code`` reads an
already compiled code object supplied by the caller; ``structure_from_source``
performs ``compile()`` only (a static derivation, not execution).

The schema is deliberately narrow and fail-closed:

* code units: exact bytes, exact length, even length, bounded;
* constants: exact type tag and value for ``int`` (abs < 2**30), ASCII ``str``
  (<= 64 bytes) and ``None``; every other constant type is unsupported;
* names: ordered ASCII ``str`` values (<= 64 bytes);
* flags and first line number;
* filename (``"<string>"`` for eval programs).

Any input outside these bounds raises ``StructureUnsupported``.  A caller must
convert that exception into ``unknown``/``blocked``; it must never be treated
as a non-match that could be ignored.
"""
import ctypes
import hashlib
import json

SCHEMA = "dynstruct-v1"
MODE = "eval"
DYNAMIC_FILENAME = "<string>"
MAX_CODE_BYTES = 512
MAX_CONSTS = 8
MAX_NAMES = 16
MAX_STRING_BYTES = 64
MAX_INT_ABS = (1 << 30) - 1
MAX_CAPTURE_EVENTS = 8
LONG_MASK = (1 << 64) - 1


class StructureUnsupported(Exception):
    """The object cannot be represented by the frozen structure schema."""


def canonical(value):
    """Canonical UTF-8-safe JSON bytes used for every digest in this tool."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_digest(data):
    return hashlib.sha256(data).hexdigest()


def _check_ascii_text(value, what):
    if type(value) is not str:
        raise StructureUnsupported("%s-not-str" % what)
    try:
        data = value.encode("ascii")
    except UnicodeEncodeError:
        raise StructureUnsupported("%s-not-ascii" % what) from None
    if len(data) > MAX_STRING_BYTES:
        raise StructureUnsupported("%s-too-long" % what)
    return data


def typed_constant(value):
    """Return the frozen typed representation of one ``co_consts`` entry."""
    if value is None:
        return {"t": "none"}
    if type(value) is bool:
        raise StructureUnsupported("bool-constant")
    if type(value) is int:
        if abs(value) > MAX_INT_ABS:
            raise StructureUnsupported("int-constant-out-of-range")
        return {"t": "int", "v": value}
    if type(value) is str:
        _check_ascii_text(value, "str-constant")
        return {"t": "str", "v": value}
    raise StructureUnsupported("constant-type-" + type(value).__name__)


def typed_name(value):
    _check_ascii_text(value, "name")
    return {"t": "str", "v": value}


def _check_code_bytes(code_bytes):
    if type(code_bytes) is not bytes:
        raise StructureUnsupported("code-bytes-type")
    if len(code_bytes) < 2 or len(code_bytes) % 2:
        raise StructureUnsupported("code-bytes-length")
    if len(code_bytes) > MAX_CODE_BYTES:
        raise StructureUnsupported("code-bytes-too-long")
    return code_bytes


def _layout_int(layout, key):
    if type(layout) is dict and type(layout.get("offsets")) is dict:
        layout = layout["offsets"]
    value = layout.get(key) if type(layout) is dict else None
    if type(value) is not int or value < 0 or value > 4096:
        raise StructureUnsupported("layout-" + key)
    return value


def inline_code_bytes(code, layout):
    """Read the freshly compiled inline code units of a code object.

    CPython 3.11+ stores the adaptive code units inline in the code object at
    the layout-derived offset; ``Py_SIZE`` holds the code-unit count.  The
    layout receipt is derived in the pinned image and validated there.  This
    helper must only be called for code objects that have never been executed
    (freshly compiled by the trusted tool), otherwise adaptive specialization
    could have rewritten the bytes.
    """
    size_offset = _layout_int(layout, "codeSizeOffset")
    adaptive_offset = _layout_int(layout, "codeAdaptiveOffset")
    units = int.from_bytes(
        ctypes.string_at(id(code) + size_offset, 8), "little", signed=True
    )
    if units < 1 or units > MAX_CODE_BYTES // 2:
        raise StructureUnsupported("code-units-range")
    raw = ctypes.string_at(id(code) + adaptive_offset, units * 2)
    return _check_code_bytes(raw)


def structure_from_code(code, layout):
    """Serialize a freshly compiled dynamic code object."""
    code_bytes = inline_code_bytes(code, layout)
    if type(code.co_filename) is not str or code.co_filename != DYNAMIC_FILENAME:
        raise StructureUnsupported("unexpected-dynamic-filename")
    consts = list(code.co_consts)
    names = list(code.co_names)
    if len(consts) > MAX_CONSTS:
        raise StructureUnsupported("too-many-constants")
    if len(names) > MAX_NAMES:
        raise StructureUnsupported("too-many-names")
    return {
        "schema": SCHEMA,
        "mode": MODE,
        "filename": DYNAMIC_FILENAME,
        "firstlineno": code.co_firstlineno,
        "flags": code.co_flags,
        "codeHex": code_bytes.hex(),
        "codeBytes": len(code_bytes),
        "names": [typed_name(name) for name in names],
        "consts": [typed_constant(value) for value in consts],
    }


def caller_descriptor(code):
    """Structural identity of an executed caller code object.

    Adaptive code units are deliberately *not* used here: an executed function
    may contain specialized/instrumented code units, so the compile-time and
    run-time byte strings need not be equal.  The descriptor uses immutable
    code-object metadata and constants/names only; the caller's source bytes
    and the verified loader are the provenance anchors.
    """
    consts = list(code.co_consts)
    names = list(code.co_names)
    if len(consts) > MAX_CONSTS:
        raise StructureUnsupported("too-many-constants")
    if len(names) > MAX_NAMES:
        raise StructureUnsupported("too-many-names")
    if type(code.co_filename) is not str:
        raise StructureUnsupported("caller-filename")
    if type(code.co_qualname) is not str:
        raise StructureUnsupported("caller-name")
    return {
        "schema": SCHEMA,
        "kind": "caller-code-object",
        "filename": code.co_filename,
        "qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno,
        "flags": code.co_flags,
        "codeUnits": len(code.co_code) // 2,
        "names": [typed_name(name) for name in names],
        "consts": [typed_constant(value) for value in consts],
    }


def structure_from_capture(capture):
    """Normalize an observer capture into the same schema as a code object.

    ``capture`` is produced by ``tools/collect_observer.py`` and contains raw
    bytes and typed values only.  The collector validates lengths before this
    function is called; this function re-validates every field.
    """
    if type(capture) is not dict:
        raise StructureUnsupported("capture-type")
    code_hex = capture.get("codeHex")
    if type(code_hex) is not str or any(ch not in "0123456789abcdef" for ch in code_hex):
        raise StructureUnsupported("capture-code-hex")
    code_bytes = _check_code_bytes(bytes.fromhex(code_hex))
    if capture.get("codeBytes") != len(code_bytes):
        raise StructureUnsupported("capture-code-length")
    if capture.get("filename") != DYNAMIC_FILENAME:
        raise StructureUnsupported("capture-filename")
    if type(capture.get("firstlineno")) is not int:
        raise StructureUnsupported("capture-firstlineno")
    if type(capture.get("flags")) is not int:
        raise StructureUnsupported("capture-flags")
    names = capture.get("names")
    consts = capture.get("consts")
    if type(names) is not list or len(names) > MAX_NAMES:
        raise StructureUnsupported("capture-names")
    if type(consts) is not list or len(consts) > MAX_CONSTS:
        raise StructureUnsupported("capture-consts")
    normalized_names = []
    for item in names:
        if type(item) is not dict or set(item) != {"t", "v"} or item["t"] != "str":
            raise StructureUnsupported("capture-name-shape")
        normalized_names.append(typed_name(item["v"]))
    normalized_consts = []
    for item in consts:
        if type(item) is not dict:
            raise StructureUnsupported("capture-const-shape")
        if item.get("t") == "none" and set(item) == {"t"}:
            normalized_consts.append({"t": "none"})
        elif item.get("t") == "int" and set(item) == {"t", "v"}:
            normalized_consts.append(typed_constant(item["v"]))
        elif item.get("t") == "str" and set(item) == {"t", "v"}:
            normalized_consts.append(typed_constant(item["v"]))
        else:
            raise StructureUnsupported("capture-const-shape")
    return {
        "schema": SCHEMA,
        "mode": MODE,
        "filename": DYNAMIC_FILENAME,
        "firstlineno": capture["firstlineno"],
        "flags": capture["flags"],
        "codeHex": code_bytes.hex(),
        "codeBytes": len(code_bytes),
        "names": normalized_names,
        "consts": normalized_consts,
    }


def caller_descriptor_from_capture(capture):
    """Normalize the observer capture of the caller code object."""
    if type(capture) is not dict:
        raise StructureUnsupported("caller-capture-type")
    if capture.get("schema") != SCHEMA or capture.get("kind") != "caller-code-object":
        raise StructureUnsupported("caller-capture-schema")
    if type(capture.get("filename")) is not str or not capture["filename"].startswith("/"):
        raise StructureUnsupported("caller-capture-filename")
    if type(capture.get("qualname")) is not str:
        raise StructureUnsupported("caller-capture-name")
    _check_ascii_text(capture["qualname"], "caller-qualname")
    if type(capture.get("firstlineno")) is not int:
        raise StructureUnsupported("caller-capture-firstlineno")
    if type(capture.get("flags")) is not int:
        raise StructureUnsupported("caller-capture-flags")
    if type(capture.get("codeUnits")) is not int or capture["codeUnits"] < 1:
        raise StructureUnsupported("caller-capture-units")
    names = capture.get("names")
    consts = capture.get("consts")
    if type(names) is not list or len(names) > MAX_NAMES:
        raise StructureUnsupported("caller-capture-names")
    if type(consts) is not list or len(consts) > MAX_CONSTS:
        raise StructureUnsupported("caller-capture-consts")
    normalized_names = []
    for item in names:
        if type(item) is not dict or set(item) != {"t", "v"} or item["t"] != "str":
            raise StructureUnsupported("caller-capture-name-shape")
        normalized_names.append(typed_name(item["v"]))
    normalized_consts = []
    for item in consts:
        if type(item) is not dict:
            raise StructureUnsupported("caller-capture-const-shape")
        if item.get("t") == "none" and set(item) == {"t"}:
            normalized_consts.append({"t": "none"})
        elif item.get("t") == "int" and set(item) == {"t", "v"}:
            normalized_consts.append(typed_constant(item["v"]))
        elif item.get("t") == "str" and set(item) == {"t", "v"}:
            normalized_consts.append(typed_constant(item["v"]))
        else:
            raise StructureUnsupported("caller-capture-const-shape")
    return {
        "schema": SCHEMA,
        "kind": "caller-code-object",
        "filename": capture["filename"],
        "qualname": capture["qualname"],
        "firstlineno": capture["firstlineno"],
        "flags": capture["flags"],
        "codeUnits": capture["codeUnits"],
        "names": normalized_names,
        "consts": normalized_consts,
    }


def structure_digest(structure):
    return digest(structure)


def code_digest_from_structure(structure):
    return bytes_digest(bytes.fromhex(structure["codeHex"]))


def structure_from_source(source, layout):
    """Compile one eval-mode source string with the frozen compiler settings.

    ``compile`` is a static derivation.  The source is never executed and the
    resulting code object is only introspected.
    """
    if type(source) is not str:
        raise StructureUnsupported("source-type")
    if len(source.encode("utf-8")) > 1024:
        raise StructureUnsupported("source-too-long")
    if "\x00" in source or "\n" in source or "\r" in source:
        raise StructureUnsupported("source-control-character")
    code = compile(source, DYNAMIC_FILENAME, MODE, dont_inherit=True, optimize=0)
    return structure_from_code(code, layout)


def quoted_data_source(value):
    """The tool-owned data-only baseline for raw double-quote interpolation.

    The frozen experiment fixture (and the reference tqdm-shaped sink class)
    interpolates the value between a double quote and a closing double quote
    without escaping.  This baseline is *not* used to confirm anything; it only
    labels a negative observation as data-only and proves that the computation
    template and its data wrapping compile to different structures.  An input
    that makes this baseline invalid is a syntax-reject input.
    """
    if type(value) is not str:
        raise StructureUnsupported("data-value-type")
    return 'str("' + value + '")'


def safe_structure_from_source(source, layout):
    """Return ``(structure, None)`` or ``(None, reason)``; never raise."""
    try:
        return structure_from_source(source, layout), None
    except StructureUnsupported as error:
        return None, "unsupported:" + str(error)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError) as error:
        return None, "syntax:" + type(error).__name__
