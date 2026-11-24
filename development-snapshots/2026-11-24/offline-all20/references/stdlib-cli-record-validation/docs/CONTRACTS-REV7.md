# Contracts revision 7 — recovery binding and tri-state paths

`protocolRevision` remains **3** and the resource-context version remains **3**.
This revision closes the three recovery counterexamples without changing the
formal experiment protocol version.  It is an implementation/contract repair,
not a version-number substitute.

## 1. One tri-state path query

`tools/resource_guard.py` exposes one small query used by both cleanup and
recovery:

```python
path_state(path) -> {"state": "absent" | "present" | "unknown", ...}
```

Rules:

- only `os.lstat` is used;
- only `FileNotFoundError` means `absent`;
- `PermissionError`, `NotADirectoryError` and every other `OSError` mean
  `unknown`;
- a symlink is `present`/`symlink`; it is never followed and never treated as
  absence;
- `lexists`, `exists` and `is_dir() == False` are never used as absence proof.

A successful stage cleanup or recovery exit requires **all** of:

1. every other resource is confirmed exited/removed;
2. `stage.removed is True`;
3. the final independent lstat is `stage.lstatAfter == "absent"`;
4. the cleanup/recovery journal was persisted successfully.

`removed=True` with a present or unknown final recheck is not a success and
must not write `accepted`, `cleanupConfirmed=true`, or settle the attempt.
A stage that was never created also uses an explicit lstat absence result.
A partial stage keeps its original `(dev, ino)` identity for recovery.

## 2. Claim-bound resource plan

Before `consume_claim`, the tool generates the tag and container name.  The
claim then binds one fixed plan:

```json
{
  "preflightId": "<preflightId>",
  "tag": "<tool-generated 16-hex tag>",
  "containerName": "stdlib-cli-preflight-<tag>",
  "imageId": "<fixed pinned image id>",
  "stageRelativePath": "preflight/evidence/<preflightId>/stage-<tag>"
}
```

- `claim.resourcePlan` contains exactly these five fields;
- `claim.resourcePlanSha256` is `guard.digest(claim.resourcePlan)`;
- the actual claim file SHA-256 remains the receipt binding
  (`receipt.claimSha256`);
- the plan is repeated, with the same digest, in the new receipt and the
  preflight/stage/container/cleanup journals;
- the plan has no project path, arbitrary name, command, environment or
  executable field.  Extra fields are a blocked ownership contradiction;
- old records without `resourcePlan` are diagnosed conservatively and are
  never auto-filled or promoted to trusted.

The preflight license is unchanged in shape and is still written by Codex after
source review: `kind=zero-target-preflight-admission`,
`protocolRevision=3`, `state=approved`, `allowedCommand=preflight`,
`maxTargetExecutions=0`, `fixturesImported=0`, bound to the final
`protocol-manifest.json` and `source-review-receipt.json`, with one unique
`preflightId`.  This author issues no license.

## 3. Recovery is bound before any action

`recover --preflight-id <id>` performs this order:

1. validate the original ID and take the same stable exclusive lock;
2. verify frozen manifest, license, source-review receipt and profile;
3. read the claim by the original ID, validate its ID/kind/revision/state,
   evidence directory, license/manifest/review bindings, and the exact fixed
   resource plan;
4. read **all** journals this recovery may consume;
5. validate the complete ownership graph;
6. only then call a container/process/stage cleanup function.

Path composition:

- expected absolute paths are composed from the fixed root, the requested ID
  and the plan's tag;
- every component is checked with `os.lstat`; a symlink, a non-directory
  intermediate component or lexical escape (`..`, absolute path) is rejected;
- `resolve()` is not used to follow links before the trust decision;
- the journal `stageDir` must equal the composed absolute path;
- the observer path is fixed to
  `preflight/evidence/<id>/observer.bt` and the observer intent argv must name
  exactly that path.

Ownership checks include: preflight ID, kind, protocol revision, role, tag,
container name, fixed image, stage path, observer path, container full ID,
creation query, client command, process identity and the role-intent/identity
relations.

Partial logs:

- a missing `preflight-intent.json` is `unknown`, never a pass;
- `stage-intent` may exist without a created stage; a present stage without an
  identity is unknown and is retained;
- `stage-started` without `stage-created` is a supported partial stage: its
  original identity is used;
- `container-intent` without `container-created` is `create-result-unknown`;
  no container is removed;
- a process intent without an identity is unknown; no signal is sent;
- a corrupt/unreadable existing journal is `incomplete`; no resource action is
  performed.

## 4. Recovery outcomes

| Condition | State | Exit |
|---|---|---|
| confirmed ownership contradiction (ID/kind/role/tag/name/image/path/container-ID/identity/plan-field mismatch) | `blocked` | 78 |
| missing new plan, missing needed proof, corrupt/read-failed journal, unconfirmable state | `incomplete` | 3 |
| lock busy | `locked` | 79 |
| processes exited, container removed/absent, stage removed, final lstat absent, recovery journal persisted | `resources-cleared` | 0 |

Recovery handles only the original ID.  It never replays the self-check, never
rewrites an old receipt or claim, and writes each result to a new
`recovery-<random>.json`.  A write failure returns 79 and never reports a
successful recovery.

## 5. Independent verifier

`tools/preflight_verify.py` now also requires the claim/receipt resource plan
and its canonical digest, and checks the plan in the preflight, stage,
container and cleanup journals.  It keeps the existing strict checks:
observer rebuild, raw re-parse with the same pure parser, integer zero,
complete unique BEGIN/END, fixed image/runtime identity, exact layout/config
bytes, and the explicit `stage.lstatAfter == "absent"` cleanup condition.
Normal recorded evidence must pass these checks; old evidence without the new
binding is rejected rather than accepted through loosened validation.

The formal runner and formal judge lifecycle/recompute gaps are recorded only;
this revision does not change the formal batch lifecycle or formal judge
recompute path.

## 6. Commands and paths

```bash
python3 tools/zero_target_preflight.py preflight
python3 tools/zero_target_preflight.py status --preflight-id <preflightId>
python3 tools/zero_target_preflight.py recover --preflight-id <preflightId>
```

- claim: `preflight/claims/<preflightId>.json`
- completed marker: `preflight/claims/<preflightId>.completed.json`
- receipt/evidence: `preflight/evidence/<preflightId>/preflight-receipt.json`
- recovery: `preflight/evidence/<preflightId>/recovery-<random>.json`
- stage: `preflight/evidence/<preflightId>/stage-<tag>`

The zero-target preflight remains unexecuted by this author.  Formal target
executions remain 0/16 and R3 remains `blocked`.
