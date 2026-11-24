#!/usr/bin/env python3
"""Capture an authorized command; derive report facts without model-supplied values.

No shell, retries, installs, network policy, or automatic report interception.
Receipts are local evidence, not authenticated attestations or a sandbox.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote


LIMIT = 65536
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
RECORD_FIELDS = {"schema_version", "run_id", "scope", "argv", "cwd", "started_at", "ended_at",
                 "state", "returncode", "stdout", "stderr", "sha256"}
GAPS = {
    "visual-inspection": "视觉检查未验证：需要实际图片查看事件及其对应页面；生成或渲染记录不能替代。",
    "interaction": "交互未验证：需要实际操作及结果状态；构建、测试或页面生成不能替代。",
    "command-history": "命令历史未验证：缺少原始尝试或拒绝记录，不能补写报错及原因。",
    "acceptance": "任务验收未验证：命令进程记录不能单独证明用户要求的最终结果。",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def valid_argv(value):
    # argv[0] names an executable; later arguments may intentionally be empty.
    return (isinstance(value, list) and bool(value) and text(value[0])
            and all(isinstance(arg, str) and "\0" not in arg for arg in value))


def exact(value, fields):
    require(isinstance(value, dict) and set(value) == fields, "missing or unknown fields")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    require(path.is_file() and path.stat().st_size <= 1024 * 1024, "invalid or oversized JSON file")
    def reject_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def digest(record):
    payload = {k: v for k, v in record.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def read_output(handle):
    handle.seek(0)
    data = handle.read(LIMIT + 1)
    complete = len(data) <= LIMIT
    try:
        value = data[:LIMIT].decode("utf-8")
    except UnicodeDecodeError:
        value, complete = data[:LIMIT].decode("utf-8", errors="replace"), False
    return value, complete


@contextmanager
def cancellation_notice():
    # A non-raising handler avoids interruption between Popen launching and
    # returning its process handle. Only the capture CLI/main thread owns it.
    require(threading.current_thread() is threading.main_thread(), "capture requires the main thread")
    pending, previous = [], {}
    def notify(signum, _frame):
        if not pending:
            pending.append(signum)
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, notify)
        yield pending
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def stop_command(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait(timeout=2)


def execute(record, argv, cwd, timeout, stdout, stderr):
    with cancellation_notice() as pending:
        if pending:
            record.update(state="interrupted", interruption_signal=pending[0])
            return
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                       stderr=stderr, shell=False, start_new_session=os.name == "posix")
        except OSError as error:
            stderr.write(str(error).encode("utf-8"))
            return
        try:
            deadline = time.monotonic() + timeout
            while True:
                if pending:
                    record.update(state="interrupted", interruption_signal=pending[0])
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    record["state"] = "timed_out"
                    break
                try:
                    code = process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
                record.update(state="exited", returncode=code)
                break
            if pending:
                record.update(state="interrupted", returncode=None, interruption_signal=pending[0])
        finally:
            # Also clean up on unexpected exceptions. If cleanup itself fails,
            # no conclusive receipt is written; the action remains uncertain.
            if record["state"] != "exited":
                stop_command(process)


def capture(path, run_id, scope, cwd, argv, timeout):
    """Create the receipt exclusively BEFORE launching, so a collision never reruns."""
    require(text(run_id) and text(scope), "run_id and scope are required")
    require(valid_argv(argv), "invalid argv")
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600,
            "timeout must be between 0 and 600 seconds")
    cwd = Path(cwd).resolve(strict=True)
    require(cwd.is_dir(), "cwd must be a directory")
    record = {"schema_version": 2, "run_id": run_id, "scope": scope, "argv": argv,
              "cwd": str(cwd), "started_at": datetime.now(timezone.utc).isoformat(),
              "state": "not_started", "returncode": None, "interruption_signal": None}
    # Inherit the existing environment; never dump it. Receipt may still contain
    # sensitive argv/output: callers must inspect the command before capture.
    with Path(path).open("x", encoding="utf-8") as receipt:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            execute(record, argv, cwd, timeout, stdout, stderr)
            record["stdout"], out_complete = read_output(stdout)
            record["stderr"], err_complete = read_output(stderr)
        record["output_text_intact"] = out_complete and err_complete
        record["ended_at"] = datetime.now(timezone.utc).isoformat()
        record["sha256"] = digest(record)
        json.dump(record, receipt, indent=2, ensure_ascii=True)
        receipt.write("\n")
    return record


def receipt_path(root, name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts and bool(path.parts), "invalid receipt path")
    candidate = root
    for part in path.parts:
        candidate /= part
        require(not candidate.is_symlink(), "symlink receipt path")
    candidate.resolve(strict=True).relative_to(root)
    return candidate


def validate_record(record, run_id, scope):
    require(isinstance(record, dict), "receipt must be an object")
    version = record.get("schema_version")
    require(type(version) is int and version in {1, 2}, "unsupported receipt schema")
    extra = {"output_complete"} if version == 1 else {"output_text_intact", "interruption_signal"}
    exact(record, RECORD_FIELDS | extra)
    require(record["sha256"] == digest(record), "receipt checksum mismatch")
    require(record["run_id"] == run_id and record["scope"] == scope, "different run or scope")
    require(valid_argv(record["argv"]), "invalid argv")
    require(text(record["cwd"]) and Path(record["cwd"]).is_absolute(), "invalid cwd")
    for key in ("started_at", "ended_at"):
        require(text(record[key]) and datetime.fromisoformat(record[key]).tzinfo is not None, "invalid timestamp")
    state, code = record["state"], record["returncode"]
    require((state == "exited" and type(code) is int) or
            (state in {"timed_out", "not_started"} and code is None) or
            (version == 2 and state == "interrupted" and code is None), "inconsistent command state")
    if version == 2:
        interrupted = record["interruption_signal"]
        require((state == "interrupted" and type(interrupted) is int and interrupted in {signal.SIGINT, signal.SIGTERM})
                or (state != "interrupted" and interrupted is None), "inconsistent interruption signal")
    key = "output_complete" if version == 1 else "output_text_intact"
    require(type(record[key]) is bool, "invalid captured text integrity")
    require(all(isinstance(record[k], str) and len(record[k]) <= LIMIT for k in ("stdout", "stderr")), "invalid output")
    return record[key]


def derive(claim, root, run_id, scope):
    row = {"id": claim["id"], "kind": claim["kind"], "receipt": claim["receipt"]}
    try:
        record = load(receipt_path(root, claim["receipt"]))
        intact = validate_record(record, run_id, scope)
        kind = claim["kind"]
        fact = {k: record[k] for k in ("argv", "cwd", "state", "returncode", "stdout", "stderr")}
        fact.update(output_text_intact=intact, output_scope="captured_snapshot_only",
                    task_completion="unverified", interruption_signal=record.get("interruption_signal"))
        if kind == "version":
            args = record["argv"]
            flags = args[1:]
            if re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?", Path(args[0]).name, re.IGNORECASE):
                if flags[:1] == ["-B"]:
                    flags = flags[1:]
            require(flags in (["--version"], ["-V"]),
                    "not a direct version query")
            require(record["state"] == "exited" and record["returncode"] == 0 and intact,
                    "version query not conclusive")
            value = (record["stdout"] + record["stderr"]).strip()
            require(bool(value) and len(value.splitlines()) == 1, "version output is not a single line")
            fact["value"] = value
        elif kind == "failure":
            require(record["state"] != "exited" or record["returncode"] != 0, "no observed failure")
            require(intact, "failure output incomplete")
        row.update(status="verified", receipt_sha256=record["sha256"], fact=fact)
    except (ValueError, OSError, UnicodeError, TypeError, OverflowError) as error:
        row.update(status="unverified", reason=str(error))
    return row


def report(plan, root):
    require(isinstance(plan, dict), "plan must be an object")
    version = plan.get("schema_version")
    require(type(version) is int and version in {1, 2}, "unsupported plan schema")
    exact(plan, {"schema_version", "run_id", "scope", "claims"} | ({"gaps"} if version == 2 else set()))
    require(text(plan["run_id"]) and text(plan["scope"]), "run_id and scope are required")
    gaps = plan.get("gaps", [])
    require(isinstance(plan["claims"], list) and isinstance(gaps, list)
            and 0 < len(plan["claims"]) + len(gaps) <= 100, "plan must contain 1..100 rows")
    ids = set()
    for claim in plan["claims"]:
        exact(claim, {"id", "kind", "receipt"})
        require(text(claim["id"]) and ID.fullmatch(claim["id"]) and claim["id"] not in ids, "invalid or duplicate claim id")
        ids.add(claim["id"])
        require(isinstance(claim["kind"], str) and claim["kind"] in {"command", "version", "failure"}, "unknown claim kind")
        require(text(claim["receipt"]), "receipt must be a path")
    for gap in gaps:
        exact(gap, {"id", "kind"})
        require(text(gap["id"]) and ID.fullmatch(gap["id"]) and gap["id"] not in ids, "invalid or duplicate gap id")
        ids.add(gap["id"])
        require(isinstance(gap["kind"], str) and gap["kind"] in GAPS, "unknown gap kind")
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), "root must be a directory")
    rows = [derive(c, root, plan["run_id"], plan["scope"]) for c in plan["claims"]]
    result = {"schema_version": version, "run_id": plan["run_id"], "scope": plan["scope"],
              "all_verified": not gaps and all(c["status"] == "verified" for c in rows), "claims": rows}
    if version == 2:
        result["gaps"] = [dict(gap, status="unverified", reason=GAPS[gap["kind"]]) for gap in gaps]
    return result


def inline(value):
    """Keep paths, diagnostics and command arguments inert in generated Markdown."""
    encoded = json.dumps(value, ensure_ascii=False)
    fence = "`" * max(1, 1 + max((len(x) for x in re.findall(r"`+", encoded)), default=0))
    return fence + " " + encoded + " " + fence


def render_markdown(result, root):
    """Render only derived process facts and explicit gaps, never arbitrary prose.

    This is a task-time generator, not a host hook. Call with a fresh report()
    result; the CLI never accepts model-supplied facts or a cached result JSON.
    """
    lines = ["命令证据（进程记录，不代表任务验收、视觉检查或交互验证）：", "",
             f"运行：{inline(result['run_id'])}；范围：{inline(result['scope'])}。", ""]
    root = Path(root).resolve(strict=True)
    for row in result["claims"]:
        prefix = f"- `{row['id']}`（{row['kind']}）："
        if row["status"] != "verified":
            lines.append(prefix + "未验证；" + inline(row["reason"]) + "。")
            continue
        fact = row["fact"]
        # Resolve again before emitting a clickable local reference. Output from
        # the command stays in its original receipt, never executable Markdown.
        path = receipt_path(root, row["receipt"])
        location = quote(str(path), safe="/:")
        state = f"`state={fact['state']}`；`exit={fact['returncode']}`"
        integrity = "记录文本完整" if fact["output_text_intact"] else "记录文本截断或含无效编码"
        value = "；查询值=" + inline(fact["value"]) if row["kind"] == "version" else ""
        lines.append(prefix + f"已记录；{state}；{integrity}{value}。[原始收据]({location})")
        lines.append(f"  命令：{inline(fact['argv'])}；目录：{inline(fact['cwd'])}。")
    for gap in result.get("gaps", []):
        lines.append(f"- `{gap['id']}`：{gap['reason']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("capture", help="execute one already-authorized command and save a new receipt")
    run.add_argument("--record", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--scope", required=True)
    run.add_argument("--cwd", type=Path, required=True)
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    render = sub.add_parser("report", help="read-only derivation of facts; no command execution")
    render.add_argument("--plan", type=Path, required=True)
    render.add_argument("--root", type=Path, required=True)
    render.add_argument("--format", choices=("json", "markdown"), default="json")
    render.add_argument("--check-markdown", type=Path,
                        help="compare a saved verification block with freshly derived Markdown; never executes commands")
    args = parser.parse_args()
    try:
        if args.action == "capture":
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            record = capture(args.record, args.run_id, args.scope, args.cwd, argv, args.timeout)
            result = {"receipt": str(args.record), "sha256": record["sha256"],
                      "state": record["state"], "returncode": record["returncode"]}
        else:
            result = report(load(args.plan), args.root)
            if args.check_markdown is not None:
                path = args.check_markdown
                require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 1024 * 1024,
                        "invalid or oversized Markdown file")
                matches = path.read_bytes() == render_markdown(result, args.root).encode("utf-8")
                print(json.dumps({"matches": matches, "all_verified": result["all_verified"]}))
                return int(not matches or not result["all_verified"])
            if args.format == "markdown":
                print(render_markdown(result, args.root), end="")
                return int(not result["all_verified"])
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if args.action == "capture" and record["state"] == "interrupted":
            return 128 + record["interruption_signal"]
        return int(args.action == "report" and not result["all_verified"])
    except (ValueError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
