# Command-derived report facts

Use for multi-command verification, retries/recovery, or exact runtime-version
reporting. This is a task-time helper, not a daemon, permission grant, general
tool wrapper or host-level output interceptor. A single simple check can cite
its original tool output without creating a journal. Other evidence types
retain their native sources.

## Capture before summarizing

Start capture with the **first** relevant baseline/test/build/type/version
check, including an expected RED or a failed implementation attempt. Do not
run tests directly until green and only then begin capturing final checks.
A later captured pass does not recover the earlier missing receipt; retain
its native output and label that structured-history gap. If Python and this
helper are available, use the capture command as the execution entry point,
not as a reporting step after an ordinary shell test.

Resolve `scripts/evidence.py` relative to the actually loaded PWA skill. Select
an existing Python 3 interpreter; do not install one implicitly. Inspect the
command's effects using the normal execution preflight. The helper runs exactly
the supplied argv with `shell=False`, inherited environment and closed stdin;
it does not make an unsafe command safe or limit filesystem/network access.

The executable must be nonblank. Later argv items may be empty strings or
whitespace when the tested CLI needs those exact inputs; capture and report
preserve them unchanged. Do not omit, trim or replace an empty argument to make
an invalid-input test runnable. NUL bytes and non-string arguments are rejected.

Keep receipts in a task-owned temporary/evidence directory outside product
files. Use a new run ID per task attempt and one scope label for the final
revision/check phase. Scope is caller-supplied provenance, not an independently
verified Git revision; change it and recapture affected checks after edits.
Do not store secrets: avoid credential-bearing arguments, environment dumps
or commands whose output may expose private data. Keep such native evidence
private and explain why the structured capture was unavailable.

Capture each relevant command directly, not a Python/shell wrapper that swallows
an inner exit code. After resolving these task-specific paths/labels:

```bash
python3 -B "$PWA_EVIDENCE_TOOL" capture \
  --record "$TASK_EVIDENCE_DIR/node.json" \
  --run-id "$TASK_RUN_ID" --scope "$TASK_SCOPE" --cwd "$PROJECT_DIR" \
  -- node --version
```

Repeat with distinct receipt paths for actual tests and each failed attempt.
No automatic retries: the same receipt path is exclusively reserved before
launch and cannot be overwritten/reused. The helper's exit **0 means receipt
written**, not command/test passed. Read the saved `state` and `returncode`.
Timeout and executable-not-found are distinct from an executed nonzero result.
For SIGINT/SIGTERM received during command execution, the main-thread helper
stops the started command's POSIX process group, waits for the direct child,
writes `state=interrupted` with no claimed command exit code, and exits 130/143
respectively. The helper temporarily handles those signals and restores the
caller's handlers afterward. On non-POSIX hosts, only the direct process is
terminated; descendant cleanup is not established by the POSIX tests.

An interrupted, failed-cleanup or empty receipt does not prove an external
operation was rolled back or never applied. Reconcile uncertain external state
before any retry. SIGKILL, host crashes, signals during receipt serialization,
or a child that deliberately escapes its process group are not cleanup
guarantees. Initial process creation can delay cancellation; after a process
handle is returned the pending cancellation is handled. No background-task
supervision or automatic retry is added. Observe action-time permissions.

## Derive the report immediately before sending

Create a small JSON plan using normal file-edit tooling. It references receipts;
it must not contain claimed values, exit codes or explanations of errors:

```json
{
  "schema_version": 1,
  "run_id": "this-task-run",
  "scope": "final-revision-checks",
  "claims": [
    {"id": "node-version", "kind": "version", "receipt": "node.json"},
    {"id": "focused-tests", "kind": "command", "receipt": "tests.json"},
    {"id": "first-attempt", "kind": "failure", "receipt": "attempt-1.json"}
  ]
}
```

```bash
python3 -B "$PWA_EVIDENCE_TOOL" report \
  --plan "$TASK_EVIDENCE_DIR/plan.json" --root "$TASK_EVIDENCE_DIR"
```

Read the returned JSON. Exit **0 means all requested facts were derived**, even
if the underlying command failed. Exit **1 means at least one unverified fact**;
exit **2 means malformed input/helper failure**. A successful gate is not a
passing test suite or proof of task completion.

- `command`: returns the exact argv, cwd, process state, exit code and captured
  output. It never infers test counts, inner command success or product quality.
  Every fact includes `output_scope=captured_snapshot_only` and
  `task_completion=unverified`; only a separate acceptance observation can
  establish the requested task's completed outcome.
- `version`: requires a successful direct `--version` / `-V` query; an optional
  single `-B` before that flag is accepted only for a Python-named executable.
  Code/module/script arguments and arbitrary extra flags are not accepted.
  After trimming outer whitespace, the intact captured text must contain one
  nonempty line. `value` is that trimmed line; original stdout/stderr remain
  unchanged in the fact, so the value is not a byte-exact quote. It identifies
  the queried executable, not a guessed version from another run or a declared dependency.
- `failure`: requires an observed non-success state and intact captured text. It
  quotes only recorded diagnostics; root-cause interpretation remains separate.

New receipts use schema v2: `output_text_intact` replaces `output_complete`,
and `interruption_signal` is null except for an observed interrupted state.
`report` still accepts schema-v1 plans and both v1/v2 receipts; v1 output is
normalized to the same narrow snapshot meaning without rewriting old files.

## Generate the verification block

For the multi-command, recovery or exact-version reports covered here, generate
the final command-verification block instead of composing its result claims:

```bash
python3 -B "$PWA_EVIDENCE_TOOL" report \
  --plan "$TASK_EVIDENCE_DIR/plan.json" --root "$TASK_EVIDENCE_DIR" \
  --format markdown > "$TASK_EVIDENCE_DIR/verification.md"
python3 -B "$PWA_EVIDENCE_TOOL" report \
  --plan "$TASK_EVIDENCE_DIR/plan.json" --root "$TASK_EVIDENCE_DIR" \
  --check-markdown "$TASK_EVIDENCE_DIR/verification.md"
```

Read the block and use it unchanged in the final response, or link the saved
block and summarize only facts it supports. `--check-markdown` rederives facts
from original receipts and checks exact UTF-8 bytes; an added or rewritten
claim returns 1. This check covers that file, not surrounding prose or the
host's final message. Command output remains in linked receipts, not executable
Markdown. A recorded exit 0 establishes only the named process result; exit 7
must remain exit 7 even when fact derivation/checking itself returns 0.

When a required check lacks native evidence, use a schema-v2 plan: retain the
same fields and add `"gaps": [{"id": "slide-layout", "kind": "visual-inspection"}]`.
Other gap kinds are `interaction`, `command-history`, and `acceptance`. `claims`
may be empty if a gap exists. IDs must be unique across both lists. Gap rows
have fixed unverified reasons and cannot supply their own status or result;
any gap makes `all_verified=false` and the report/check exit 1, while still
producing the block. Do not remove a gap to make the gate green. Only resolve
it with the actual observation; command receipts cannot certify native visuals.

Keep source facts, observed artifact/interaction results and causal hypotheses
separate from this command block, with their original tool/event references.
Do not add an unrecorded earlier attempt in explanatory prose. An expected
shell restriction is a hypothesis until an actual rejection is retained.

Before sending, match every reported command result, precise runtime version
and attempted-error-history detail to the corresponding derived fact. Preserve
its command identity and scope. Translate/present facts concisely; do not add
new attempts, diagnoses or versions in surrounding prose. Missing evidence
must be omitted or labeled **未验证 / unverified**, with its reason. Report test
counts only after actually inspecting the relevant complete test output.

Do not hand-author/backfill receipts, reuse another task's receipt, or rerun a
mutation just to obtain one. For already executed work, use the original tool
trace as evidence and disclose that the structured gate was not used. A safe,
authorized local check may be rerun explicitly as a new observation.

## Limits

Checksums detect accidental edits, not deliberate forgery; these files are not
signed attestations. Receipt paths cannot escape the selected root or traverse
symlinks, but this is not protection against hostile concurrent filesystem
changes. Retained text is capped at 64 KiB per stream; truncation/non-UTF-8 sets
`output_text_intact=false` and blocks version/failure facts. This flag only
describes the captured byte snapshot: it does not prove EOF from all descendants
or that an asynchronous task finished. A parent that exits while children still
write can omit later output even when the captured text is intact. Do not use
capture to supervise persistent/background services; inspect their actual final
state separately using the functional acceptance workflow. Command exit/state
can still be reported, not unseen output details. Temporary command output uses
disk and is not a resource sandbox. The direct command timeout defaults to
120 s (maximum 600 s). No command is rerun by `report`.

The script cannot certify arbitrary free-text reasoning or intercept every
Codex response. Markdown generation and checking are explicit task-time steps,
not an automatic final-message hook or a semantic audit of arbitrary text.
The guarantee is narrower: **facts generated from captured
records are deterministic**, and missing references cannot become verified
facts through a model-supplied value. Keep final prose within those facts and
retain normal artifact/behavior checks and trace review.
