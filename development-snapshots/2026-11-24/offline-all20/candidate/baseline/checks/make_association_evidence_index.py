#!/usr/bin/env python3
"""Build the external evidence index for B5-B7 association recovery.

The index is deliberately outside ``protocol-manifest.json``: it binds raw
stdout/stderr, return codes, exact commands, source snapshots and result-file
digests for the RED, interim and final invocations.  It never deletes or
rewrites an evidence directory and never imports product code.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "checks" / "evidence-runs"
OUT = ROOT / "checks" / "evidence-index.json"


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify(label, directory):
    text = (label or "") + " " + directory.name
    lowered = text.lower()
    if "red" in lowered:
        return "red"
    if "final" in lowered:
        return "final"
    if "interim" in lowered or "smoke" in lowered or "mid" in lowered:
        return "interim"
    return "other"


def recompute_bundle(directory):
    hasher = hashlib.sha256()
    files = sorted(path for path in directory.iterdir()
                   if path.is_file() and path.name != "capture.json")
    for path in files:
        hasher.update(path.name.encode("utf-8") + b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def entry(directory):
    relative = str(directory.relative_to(ROOT))
    files = {path.name: {"sha256": sha_file(path), "bytes": path.stat().st_size}
             for path in sorted(directory.iterdir()) if path.is_file()}
    command = {}
    capture = {}
    if (directory / "command.json").is_file():
        command = json.loads((directory / "command.json").read_text())
    if (directory / "capture.json").is_file():
        capture = json.loads((directory / "capture.json").read_text())
    result_path = command.get("resultFile")
    result_sha = capture.get("resultFileSha256")
    if result_path and Path(result_path).is_absolute():
        result_file = Path(result_path)
    elif result_path:
        result_file = ROOT / result_path
    else:
        result_file = None
    result_present = bool(result_file and result_file.is_file())
    result_matches = bool(result_present and result_sha
                          and sha_file(result_file) == result_sha)
    complete = all((directory / name).is_file() for name in (
        "command.json", "capture.json", "source-before.json",
        "source-after.json", "stdout.bin", "stderr.bin", "returncode.txt"))
    source_before_digest = None
    source_after_digest = None
    if (directory / "source-before.json").is_file():
        source_before_digest = json.loads(
            (directory / "source-before.json").read_text()).get("digest")
    if (directory / "source-after.json").is_file():
        source_after_digest = json.loads(
            (directory / "source-after.json").read_text()).get("digest")
    captured_bundle = capture.get("bundleSha256")
    recomputed_bundle = recompute_bundle(directory) if complete else None
    return {
        "directory": relative,
        "label": capture.get("label") or command.get("label"),
        "kind": classify(capture.get("label") or command.get("label"), directory),
        "completeCapture": complete,
        "captureSha256": files.get("capture.json", {}).get("sha256"),
        "commandSha256": files.get("command.json", {}).get("sha256"),
        "argv": command.get("argv"),
        "cwd": command.get("cwd"),
        "returncode": capture.get("returncode"),
        "stdoutSha256": files.get("stdout.bin", {}).get("sha256"),
        "stderrSha256": files.get("stderr.bin", {}).get("sha256"),
        "returncodeFileSha256": files.get("returncode.txt", {}).get("sha256"),
        "sourceBeforeDigest": source_before_digest,
        "sourceAfterDigest": source_after_digest,
        "sourceChangedDuringInvocation": capture.get("sourceChangedDuringInvocation"),
        "sourceSnapshotMatchesCapture":
            source_before_digest == capture.get("sourceBeforeDigest")
            and source_after_digest == capture.get("sourceAfterDigest"),
        "resultFile": result_path,
        "resultFileSha256": result_sha,
        "resultFilePresent": result_present,
        "resultFileMatchesCapture": result_matches,
        "capturedBundleSha256": captured_bundle,
        "recomputedBundleSha256": recomputed_bundle,
        "bundleVerified": bool(captured_bundle and recomputed_bundle
                               and captured_bundle == recomputed_bundle),
        "files": files,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", default=str(EVIDENCE_ROOT))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    evidence_root = Path(args.evidence_root).resolve()
    out = Path(args.out).resolve()
    if not evidence_root.is_dir():
        print("missing evidence root: " + str(evidence_root), file=sys.stderr)
        return 1
    entries = [entry(path) for path in sorted(evidence_root.iterdir())
               if path.is_dir()]
    manifest_path = ROOT / "protocol-manifest.json"
    manifest_sha = sha_file(manifest_path) if manifest_path.is_file() else None
    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
    payload = {
        "kind": "association-recovery-evidence-index",
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "evidenceRoot": str(evidence_root.relative_to(ROOT)),
        "entryCount": len(entries),
        "completeEntryCount": sum(1 for item in entries if item["completeCapture"]),
        "bundleVerifiedCount": sum(1 for item in entries if item["bundleVerified"]),
        "incompleteCaptures": [
            {"directory": item["directory"], "label": item["label"]}
            for item in entries if not item["completeCapture"]],
        "redEntries": [item["directory"] for item in entries if item["kind"] == "red"],
        "interimEntries": [item["directory"] for item in entries
                           if item["kind"] == "interim"],
        "finalEntries": [item["directory"] for item in entries
                         if item["kind"] == "final"],
        "otherEntries": [item["directory"] for item in entries if item["kind"] == "other"],
        "protocolManifestSha256": manifest_sha,
        "protocolManifestFileCount": manifest.get("fileCount"),
        "entries": entries,
        "invariants": {
            "uniqueDirectories": len({item["directory"] for item in entries}) == len(entries),
            "allCompleteCapturesVerified": all(
                item["bundleVerified"] and item["sourceSnapshotMatchesCapture"]
                for item in entries if item["completeCapture"]),
            "allFinalCapturesComplete": all(
                item["completeCapture"] for item in entries if item["kind"] == "final"),
            "allResultFilesMatch": all(
                item["resultFileMatchesCapture"] for item in entries
                if item["completeCapture"] and item["resultFile"]),
            "sourceChangedOnlyByExplicitEdits": all(
                item["sourceChangedDuringInvocation"] is False
                for item in entries if item["completeCapture"]),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "entryCount": payload["entryCount"],
        "completeEntryCount": payload["completeEntryCount"],
        "bundleVerifiedCount": payload["bundleVerifiedCount"],
        "incompleteCaptures": payload["incompleteCaptures"],
        "red": len(payload["redEntries"]),
        "interim": len(payload["interimEntries"]),
        "final": len(payload["finalEntries"]),
        "invariants": payload["invariants"],
        "sha256": sha_file(out),
    }, sort_keys=True))
    return 0 if all(payload["invariants"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
