**Confirmed scoped defects**

1. **`confirmed` does not prove the actual input path.**  
   `run_probe` records `containsProbe = probe in arg`; `verification_report` treats that as input reachability. The four probes are fixed. Reproducible false positive:

   ```python
   def route(value):
       return eval("str(101+37)#")
   ```

   Probe index 1 is `str(101+37)#`. The source ignores `value`, evals the same constant, `containsProbe` is true, `evalWitness` is true, all four runs are `observed`, and the decision becomes `confirmed` even though no untrusted input reached the sink. This is a safety blocker for `confirmed`. Fixed probes plus substring/equality checks cannot establish data flow; use an unpredictable per-run nonce or taint tracking. Exact fixed-probe equality would still be forgeable if the source embeds the probe.

2. **Project source can forge the child trace.**  
   `passive_source` allows `import builtins, os` and `builtins.print = ...`; the tamper check only verifies `builtins.eval`/`exec` and the monitoring event mask. Source executed by the worker can replace `builtins.print`, write fake JSON to fd 1, and the parent will accept it because it does not require the trace `pointId` or `callee` to match. This is source-driven, not same-UID controller tampering. If project source is adversarial, it is a safety blocker; under the stated “not an in-process boundary / self-attested” scope, it is a known limitation—but then `confirmed` is not trustworthy against malicious source.

3. **Final decision logic lacks point/callee matching.**  
   `calls=[c for r in runs for c in r['trace'].get('calls',[])]`; confirmation accepts any call with `containsProbe`/`exactStr` and any return witness in the same run. Exclusion accepts `all(c['exactStr'])`. It never checks `c['pointId']==point['id']`, `c['callee']==point['callee']`, or return `pointId`. With the trusted worker these are currently set, so this is defense-in-depth; it also makes defects 1–2 exploitable. Fix by requiring exact point identity, callee identity, and matched return witness.

**Reasoning check / conservative limitations**

- The narrow exclusion path looks sound for the supported forms: the guard must immediately dominate the single sink statement, the guard arm must exit, no `var` store may occur between guard and sink, type flow is restricted to exact-str constructions, and finite sets are restricted to literal-expression contents. This is deliberately narrow, not a safety blocker. Unsupported flows return `unknown`.
- `POLICY['outputBytes']=262144` and `RLIMIT_FSIZE` use 262144, but the parent reads/rejects above 32768, so valid large traces become `unknown`. Conservative.
- Fixed `/tmp/probe-N` directories are not unique/cleaned; reruns can fail on collision. Conservative/reproducibility.
- Snapshot closure binds code, dependencies, recipes, declared policy, `imageId`, controller hashes, and static snapshot. It does not bind actual container flags/runtime; self-attested. `freeze` can create a mismatched `staticSha256` that `verify` later rejects; verify catches it, but freeze should enforce consistency.
- Current tests cover missing files and dependency mutation, but not source trace forgery, observer callback replacement, worker-hash/recipe/staticSha mismatch, or no-sink control.

The supplied `runtime-evidence.txt` is internally consistent for two `confirmed` and two `excluded` cases. `skf-fixed-control.py` has no result there, and no-sink control is not demonstrated in S2. No R3 or live acceptance is claimed.
