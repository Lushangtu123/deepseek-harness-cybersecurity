**Confirmed blockers**

1. **Fresh challenge is not bound to the actual probe execution.** Confirmation checks only `containsProbe` plus `evalWitness`, not provenance. This source is accepted and confirmed:
```python
import re
def route(value):
    m = re.search(r'[a-f0-9]{64}', value)
    return eval("'" + m.group(0) + "'")
```
For probes 2/3, the eval argument contains the challenge and eval returns the challenge, but the evaluated text is only a quoted hex string. The supplied expression/statement was not executed. This is a false-confirm blocker; require exact probe argument equality or a real provenance/taint rule, not substring.

2. **Exec witness can come from source state, not the exec probe.** `returned()` reads `__harness_probe__` from the eval/exec frame locals. Source can set a local/global of that name and then eval a comment containing the probe, yielding `containsProbe` and an apparent `execWitness` without executing the assignment probe. Reject source uses/rebindings of `__harness_probe__`, or verify the marker assignment executed inside the exact probe.

3. **Source preflight is bypassable and does not return `unknown`.** `passive_source` checks direct AST attributes, but accepts `open('/proc/self/fd/3','w').writelines(...)` and `eval("__import__('os')._exit(0)")`. Thus raw writes/exit/observer access are reachable despite the stated preflight guarantee. This is a trusted-result/preflight blocker; the “not an anti-tamper proof” caveat does not make the source `unknown`, as claimed.

**Confirmed scope regressions**

4. **Default parameters are not rejected.** `string_type_flow` rejects only `len(args)>1` and `*args/**kwargs`; it ignores `fn.args.defaults` and `kw_defaults`. `def route(value=callback()): ...` can still support an exclusion proof, contradicting the stated default-parameter rejection and allowing definition-time side effects.

5. **Verifier crashes instead of returning `unknown`.** `work.mkdir(mode=0o700)` lacks `exist_ok`; rerunning `/tmp/probe-0` raises `FileExistsError`. Also `json.loads(raw)` is uncaught when child exit is 0 with empty/invalid output, so the report path aborts rather than conservatively returning `unknown`.

**Conservative limitation**

6. `finite-literal-set` uses `literal_expression(v.value)` on the string content. Common literal sets such as `("admin", "guest")` are rejected as `unknown` because `ast.parse("admin")` is a Name. This is over-rejection, not a safety false-positive.
