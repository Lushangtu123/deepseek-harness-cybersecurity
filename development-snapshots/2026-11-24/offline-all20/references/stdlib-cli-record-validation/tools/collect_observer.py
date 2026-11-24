#!/usr/bin/env python3
"""Collector for the out-of-process structure observer.

This is a thin, pure adapter around one explicitly selected frozen parser: it
reads one raw stream, recomputes the observation from those exact bytes, and
writes a **new** receipt file (``O_EXCL``; an existing file is never
overwritten).  ``--observation-protocol`` is required and explicit:
``legacy`` selects the historical :mod:`observation_pure`, ``buffer-v1``
selects the retained :mod:`buffer_protocol`, and ``buffer-v2`` selects the
strict :mod:`buffer_protocol_v2`.  The buffer-v2 path additionally requires the
explicit tool-fixed ``--framing-policy end-lf-padding-v1``; legacy and
buffer-v1 keep their old arguments and wire bytes unchanged.  There is no
content sniffing and no fallback.  Historical v1/legacy collection is available only through this
explicit choice; the new zero-target preflight always passes ``buffer-v2``.
The preflight verifier, runner and judge call the selected pure parser
directly, so a stored ``observation.json`` is never trusted as evidence by
itself.

The collector never reads target stdout/stderr, never trusts a target
self-report, and never executes anything.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import buffer_protocol  # noqa: E402
import buffer_protocol_v2  # noqa: E402
import observation_pure  # noqa: E402


def write_new_bytes(path, payload):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return observation_pure.sha256_bytes(payload)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation-protocol", required=True,
                        choices=("legacy", "buffer-v1", "buffer-v2"))
    parser.add_argument("--framing-policy",
                        choices=(buffer_protocol_v2.FRAMING_POLICY,))
    parser.add_argument("--raw", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--caller-path", required=True)
    parser.add_argument("--call-offset", type=int, required=True)
    parser.add_argument("--max-events", type=int, default=observation_pure.MAX_EVENTS)
    parser.add_argument("--target-pid", type=int, required=True)
    parser.add_argument("--target-uid", type=int, required=True)
    parser.add_argument("--raw-truncated", action="store_true")
    parser.add_argument("--forced-stop", action="store_true")
    parser.add_argument("--drain-incomplete", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.observation_protocol == "buffer-v2":
        if args.framing_policy is None:
            print(json.dumps({"state": "invalid", "events": 0,
                              "errors": ["framing-policy-missing"]}))
            return 2
        if args.framing_policy != buffer_protocol_v2.FRAMING_POLICY:
            print(json.dumps({"state": "invalid", "events": 0,
                              "errors": ["framing-policy-unknown"]}))
            return 2
    elif args.framing_policy is not None:
        print(json.dumps({"state": "invalid", "events": 0,
                          "errors": ["framing-policy-not-applicable"]}))
        return 2
    if os.path.lexists(args.out):
        print(json.dumps({"state": "invalid", "events": 0, "errors": ["out-exists"]}))
        return 4
    with open(args.raw, "rb") as handle:
        raw = handle.read()
    if args.observation_protocol == "legacy":
        parser_module = observation_pure
    elif args.observation_protocol == "buffer-v1":
        parser_module = buffer_protocol
    else:
        parser_module = buffer_protocol_v2
    parser_kwargs = {
        "max_events": args.max_events,
        "raw_truncated": args.raw_truncated,
        "require_events": None,
        "forced_stop": args.forced_stop,
        "drain_incomplete": args.drain_incomplete,
    }
    if parser_module is buffer_protocol_v2:
        parser_kwargs["framing_policy"] = args.framing_policy
    receipt = parser_module.parse_receipt(
        raw,
        args.run_id,
        args.tag,
        args.caller_path,
        args.call_offset,
        args.target_pid,
        args.target_uid,
        **parser_kwargs,
    )
    payload = json.dumps(receipt, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    try:
        digest = write_new_bytes(args.out, payload)
    except FileExistsError:
        print(json.dumps({"state": "invalid", "events": 0, "errors": ["out-exists"]}))
        return 4
    print(json.dumps({
        "state": receipt["state"],
        "events": len(receipt["events"]),
        "errors": receipt["errors"],
        "observationProtocol": args.observation_protocol,
        "observationSha256": digest,
    }))
    return 0 if receipt["state"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
