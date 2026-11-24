# Damaged-record validation and effective-state contract

Protocol revision **3** is unchanged. This contract is additive to the existing
recovery, association and formal-admission contracts. It covers only the small
record surface consumed by cleanup, query/status, reservation and settlement.
It is not a general JSON schema layer and does not authorize automatic repair.

## 1. Read and classify before mutation

Every recovery consumer first reads the original bytes and classifies the
individual fields it may consume or write. Classification is pure: it performs
no JSON rewrite, no metadata reconstruction, no empty-history normalization and
no "legacy" relabeling.

`recordState` is one of:

| value | meaning |
| --- | --- |
| `valid` | all documented fields present and of the expected type |
| `legacy` | at least one documented additive field is missing or `null` |
| `invalid` | a present field has a wrong container/member/recognized type |
| `unreadable` | bytes could not be read or parsed as a JSON object |

`recordIssues` is a list of reason strings. It is diagnostic only; it is never
used as an excuse to replace a damaged record.

## 2. Minimum validated surface

| field | missing / `null` | present |
| --- | --- | --- |
| `resourceIntent`, `resourceIdentity` | legacy-compatible | must be an object; `[]`, strings and other containers are invalid |
| `cleanupReceipts` | explicit legacy-compatible | must be a list; members must be objects with recognized `state`/`confirmed`/`checkedAt` types and optional resource phase |
| `cleanup` | legacy-compatible | must be an object when present; recognized `state`, `confirmed`, `checkedAt`, `finalStageCheck`, `reason`, phase and nested stage/container status types must agree |
| `cleanupCheck` | legacy-compatible | must be an object when present; recognized protocol/state/count/timestamp/phase types must agree |
| `associatedPrepareIds`, `associationIntents` | legacy-compatible | existing selector/protocol/member types are validated independently |
| process, stage, container and resource-proof fields | legacy-compatible | only the fields consumed by recovery are checked |

Unknown compatible keys are preserved. A malformed resource/history field does
not erase an independently valid identity or relationship field. A malformed
relationship field is never guessed, completed or auto-linked.

## 3. Effective state

Query and status expose raw bytes plus additive read-only truth:

* `recordState`
* `recordIssues`
* `effectiveCleanupConfirmed`
* `effectiveReservationHeld`

For `valid` and `legacy`, effective state preserves the original raw state.
For `invalid` and `unreadable`, effective truth is fail-closed:

```
effectiveCleanupConfirmed = false
effectiveReservationHeld = true
```

A raw `cleanup.confirmed=true` or `reservationHeld=false` may remain visible in
the original bytes, but it is not effective state. Query and status never write.

The same shared classification is consumed by reservation/new-task checks,
start/association checks, cleanup/hold boundaries and settlement. A damaged or
unknown record therefore cannot release a reservation, settle a task or start
related work.

## 4. Preservation and scope behavior

* An invalid or unreadable record remains **exactly** its original file bytes.
* No empty list is substituted for a string/object; no string/object is coerced
  into a list; no unknown metadata is reconstructed.
* Invalid parent: valid known children and an independently valid parent plan
  are held; the invalid parent bytes are untouched; no resource operation runs;
  the command returns incomplete **3**.
* Invalid child: the damaged child bytes are untouched, valid readable siblings
  are individually held, and the parent cleanup/settlement cannot become
  successful.
* Relationship contradiction (`D2`): the whole known directory scope is read
  and classified first. Only individually validated, writable records are held.
  Contradictory/damaged bytes are untouched. The command returns **78** with an
  explicit blocked reason and any hold failures after the valid holds.
* Lock-busy **79** and CLI selector/usage **2** semantics are unchanged.
* No sidecar replacement record, automatic migration or automatic repair is
  invented.

## 5. Receipt append boundary

`_append_cleanup_receipt` and every hold/update boundary validate the existing
history **before** writing. A string/object history or malformed member raises
a record-validation failure; it is never silently converted to `[]`. A valid
canceled append (checking/incomplete state) may leave history unchanged, but a
completed receipt always carries recognized `state`, boolean `confirmed`, a
timestamp and an optional known resource phase.

## 6. Tests

`checks/run_record_validation_checks.py` is the focused offline suite. It uses
private synthetic records and effect-free resource doubles only. It covers
legacy/empty controls, invalid intent/history/current fields, invalid
parent/child combinations, multiple children with one contradiction, read and
partial-enumeration failures, hold-write failure, query/status raw-vs-effective,
reservation/settlement refusal, exact byte equality on damaged objects, and
normal/repeated/restored-fixture recovery. Existing affected suites remain
required.
