# Damaged-record validation support

| condition | classification | command result | resource operations | evidence |
| --- | --- | --- | --- | --- |
| missing/`null` additive field | `legacy` | existing behavior | existing behavior | focused legacy controls |
| empty valid object/list control | `valid` | existing behavior | existing behavior | focused empty controls |
| invalid `resourceIntent`/`resourceIdentity` | `invalid` | `3` | 0 | B11 focused checks |
| malformed `cleanupReceipts` member/container | `invalid` | `3` | 0 | B12 focused checks |
| malformed `cleanup`/`cleanupCheck` recognized field | `invalid` | `3` | 0 | focused current-field checks |
| unreadable/JSON/IO plan or attempt | `unreadable` | `3` | 0 | focused read/IO checks |
| relationship contradiction | `invalid` / `78` | `78` after valid holds | 0 | D2 focused checks |
| lock busy | unchanged | `79` | 0 | existing recovery suite |
| selector usage | unchanged | `2` | 0 | existing recovery suite |

The focused suite is `checks/run_record_validation_checks.py`; its raw output is
captured by `checks/capture_suite.py` in a new directory under
`checks/evidence-runs/`. Every run records exact argv/cwd/PATH, raw
stdout/stderr/exit, source hashes before and after, and the result digest.

The product change is confined to `tools/experiment_runner.py`; protected judge,
parser, observer, preflight, compiler, launcher, templates, fixtures and
experiment plan remain byte-identical to the frozen baseline. No Docker, BPF,
bpftrace, compiler, selfcheck, fixture, target, preflight, admission, model
reviewer, deployment, GitHub push or Mac permission is used. Formal targets
remain `0/16`; R3 remains blocked.
