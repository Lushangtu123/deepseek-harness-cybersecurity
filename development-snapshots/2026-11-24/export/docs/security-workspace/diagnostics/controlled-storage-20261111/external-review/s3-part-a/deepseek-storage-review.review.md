## Scope / verdict

Reviewed part A only: `policy_for/validate_policy`, `private/read_bytes`, `ReadBudget`, `source_snapshot`, `archive_plan`, `validate_plan`, `validate_manifest`, plus the supplied `storage_module/freeze/verify/_validate_attempt` context. I did not execute anything. **No R3 or live-acceptance claim.**

I found **one record-completeness blocker in part A** (conditional on `settled_job` not independently enforcing client records), plus several concrete plan-validation/reporting conditions. I did **not** find a new blocker in the readable-regular/`nlink==1`/root-CID/read-budget/docker-config-empty checks themselves.

## Blocker A1 — incomplete client-record inventory in `source_snapshot`

`source_snapshot` validates the **log file names** exactly:

```python
expected={f'client-{i}.{extension}' for i in range(1,count+1) ...}
actual={name for name in files if name.startswith('client-')}
if actual!=expected: raise ValueError('client log inventory mismatch')
```

but it never requires `clients` to contain exactly one record for every index `1..count`. It only validates the events that happen to be present:

```python
count=job.get('clientCounter',0); clients=job.get('clients',[])
if type(count) is not int or not 0<=count<=9999 or not isinstance(clients,list) or len(clients)>128:
    raise ValueError('invalid client inventory')
...
for event in clients+([job['createClient']] if 'createClient' in job else []):
    if not isinstance(event,dict) or type(event.get('index')) is not int or not 1<=event['index']<=count:
        raise ValueError('invalid client record')
    if event.get('notStarted') is not True and (...):
        raise ValueError('client exit unconfirmed')
```

Missing indices are accepted, and duplicate indices are accepted. The `len(clients)>128` cap does not fill or require the remaining records.

**Synthetic reproduction:** use the `archive.test` `job()` fixture; set `clientCounter=2`, `clients=[]`, create empty `client-1.stdout`, `client-1.stderr`, `client-2.stdout`, `client-2.stderr` with mode `0600`. With the fixture’s settled state/cleanup, `source_snapshot` returns an entry and `archive_plan` emits it. Also `clientCounter=1` with `clients=[{index:1,...},{index:1,...}]` passes. This violates “complete record and client log inventory” and can archive an incomplete record.

**Condition:** if `settled_job(job)` (not included in this part) independently enforces exactly one record per client index, this collapses to a false positive. The part-A code does not enforce it. Fix: require exactly one event per index, and validate `createClient` separately.

## Condition A2 — `validate_plan`/`validate_manifest` accept forged ancillary metadata

`validate_plan` checks the top-level key set and important fields, but does **not** semantically validate `cacheIdentity`, `scanned`, `hashedBytes`, or `retained`. A rehashed plan with:

```python
bad['cacheIdentity']={'device':0,'inode':0}
bad['scanned']=10**9
bad['hashedBytes']=0
bad['retained']=[{'source':'/arbitrary','reason':'x'}]
bad['planSha256']=digest({k:v for k,v in bad.items() if k!='planSha256'})
```

is accepted by `validate_plan`. This is **not source-move safety** if `archive_apply` re-snapshots and ignores these fields, but it is an audit/reporting blocker if plan status/reports trust them.

`validate_manifest` also does not validate `rootIdentity` at all beyond key presence. A rehashed entry with `rootIdentity=None`, or extra/malformed keys, passes `validate_plan`. If apply indexes `rootIdentity`, this becomes a `TypeError`; if it compares it, binding is incomplete. Fix strict shapes/types for `rootIdentity` and exact file-meta fields.

## Condition A3 — malformed `generatedAt` raises `TypeError`, not `ValueError`

`validate_plan` calls:

```python
generated=datetime.fromisoformat(plan['generatedAt'])
```

without first requiring `generatedAt` to be a string. Rehash a valid plan with `generatedAt=None`; `validate_plan` raises `TypeError`, not a clean `ValueError`/`StorageError`. If the CLI catches only `ValueError`, this is a malformed-plan crash condition. Fix type/tz checks before parsing.

## Condition A4 — `read_bytes(root_cid=True)` does not reject group/other-writable root files

`read_bytes` allows `root_cid=True` based on ownership/nlink/type, but does not check mode:

```python
allowed=value.st_uid==os.geteuid() or root_cid and value.st_uid==0
```

So a root-owned regular file with mode `0666` would be read. `source_snapshot` separately rejects root-CID `mode & 0o022`, so this is **not** a blocker in the supplied part-A CID path; it becomes relevant if another caller uses `read_bytes(..., root_cid=True)` directly for CID/trusted bytes. Condition/false positive for A.

## Conservative limitations, not safety blockers

- `source_snapshot` caps `len(clients)>128` while `clientCounter` allows `9999` and log-name inventory allows up to `20000` entries; valid very-large-client tasks are retained/rejected conservatively.
- `bounded_names(cache,1000)` makes `archive_plan` raise when the cache has more than 1000 entries instead of returning `retained`; bounded scan limitation.
- The estimate in `archive_plan` intentionally rejects batches before 64 MiB unique content; conservative, not a correctness bug.
- Same-UID replacement races and post-check `docker-config` changes remain within the known “not atomic snapshot” limitation.
- `finishedAt` future checking uses real `now()` rather than the injected plan `clock`; test-clock behavior only, not live safety.

## Out of scope / red evidence

The `limits-red` failures are in part B functions not reviewed here: `verify_archive` reads the archive before charging/checking the budget, and `load_transaction` does not reject the rehashed `../escape` transaction-manifest path in that test. I do not classify them as part-A findings, but they are not false positives for part B. S4/live Linux/root-CID/native-flow acceptance remains pending; external review is not R3.
