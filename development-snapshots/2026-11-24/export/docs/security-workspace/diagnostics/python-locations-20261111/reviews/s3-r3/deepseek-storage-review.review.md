Scoped conclusion: the two binder changes are sound; I found no new safety blocker in this diff.

- `if(!rules.has(f?.rule))return f` correctly preserves `null` and non-rule rows without throwing.
- `m.index===index-1` correctly prevents positional misbinding when mappings are reordered or absent.
- Eligible counting and `summary` remain scoped to rule rows. No bypass found through null/non-rule rows.
- The supplied tests cover null preservation and wrong-index rejection. The wrong-index test is single-row only, but the index logic appears correct with interleaved rows.

VM historical guard: duplicate same-line candidates and missing-positive points reject before freeze, as required. Requiring `file.state==='completed'` is correct. The zero-point exception is narrow: it requires `file.points.length===0`, the predeclared id, and `truth==='negative'`.

Residual concrete guard gaps, diagnostic provenance rather than R3/live blockers:

1. The zero-point exception is not tied to the expected historical path/file name or source digest. A row with `id==='skf-viewer-authored-fix'` and `truth==='negative'` could be relabeled to another completed zero-point inventory file and still bind to `pointId:null`.
2. In the one-match branch, the matched point’s `id`/source identity is not validated before emitting `pointId`; a malformed matching point can become `pointId:null`, weakening historical provenance.

Counterexample evidence exercises duplicate and missing-positive rejection only; it does not cover those two paths. These are conservative hardening limitations, not claims of builtin identity, taint, vulnerability confirmation, R3, or live acceptance.
