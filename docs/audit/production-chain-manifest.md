# Production Chain Manifest

> **The question this document answers:** *is this capability actually in the real
> production chain?*

It exists because the Gate G.0 audit found capabilities that were implemented, had
passing unit tests, and were still never called by any production path —
`timebase.py`, `narration_coverage.py`, `audio_program.py` and the whole
`review`/repair contract. A file existing is not evidence. A test passing is not
evidence. Only a **production caller** is evidence.

The machine-readable form is [`production-chain-manifest.json`](production-chain-manifest.json).
Its invariants are enforced by `tests/test_production_chain_manifest.py`, so this
document cannot mark a capability `WIRED` without naming a caller that exists.

## Status vocabulary

| Status | Means |
|---|---|
| `WIRED` | a production caller exists, is named, and is in git |
| `PARTIALLY_WIRED` | reachable from some production path, but not the fast path, or not on real media |
| `NOT_WIRED` | implemented and possibly tested, but no production caller |
| `JOB_SPECIFIC_ONLY` | exists only as a per-job script outside version control |
| `EXPERIMENTAL_ONLY` | reachable only from a test or evaluation harness |
| `DEPRECATED` | superseded and retained |
| `UNKNOWN` | not determined |

## Enforced invariants

1. `WIRED` ⇒ `production_caller` is not null
2. `WIRED` ⇒ `git_tracked` is true
3. `third_sku_ready` ⇒ `wiring_status == WIRED`
4. every P0 module has a non-null production caller
5. `implementation` path exists on disk
6. `stage` is one of the eight semantic stages

## Summary

| Stage | Capability | Status | 3rd SKU ready |
|---|---|---|---|
| PREPARE | source ingestion and immutability | `WIRED` | yes |
| PREPARE | material and candidate identity | `PARTIALLY_WIRED` | no |
| UNDERSTAND SHOTS | visual segmentation | `WIRED` | yes |
| UNDERSTAND SHOTS | semantic / action grouping | `NOT_WIRED` | no |
| UNDERSTAND SHOTS | material capacity estimation | `NOT_WIRED` | no |
| PLAN THE EDIT | action-aware timeline range validation | `WIRED` | yes |
| PLAN THE EDIT | executable timeline contract | `PARTIALLY_WIRED` | no |
| FINISH THE PICTURE | source-range execution through the timebase invariant | `WIRED` | yes |
| FINISH THE PICTURE | read-only picture measurement | `PARTIALLY_WIRED` | no |
| FINISH THE PICTURE | product authenticity protection | `PARTIALLY_WIRED` | no |
| FINISH THE PICTURE | KEEP / REVIEW / CORRECT decision | `WIRED` | yes |
| FINISH THE PICTURE | DaVinci Resolve execution | `JOB_SPECIFIC_ONLY` | no |
| PLAN THE WORDS | commercial narration coverage | `WIRED` | yes |
| PLAN THE WORDS | spoken duration validation | `PARTIALLY_WIRED` | no |
| PLAN THE WORDS | typography policy validation | `PARTIALLY_WIRED` | no |
| PLAN THE WORDS | typography execution | `JOB_SPECIFIC_ONLY` | no |
| BUILD THE AUDIO | audio program verification (FIT / SYNC / RHYTHM) | `WIRED` | yes |
| BUILD THE AUDIO | audio plan contract | `PARTIALLY_WIRED` | no |
| BUILD THE AUDIO | audio rendering and mixing | `JOB_SPECIFIC_ONLY` | no |
| ASSEMBLE & MASTER | packaging, encode/remux, final master | `NOT_WIRED` | no |
| REVIEW & REPAIR | review contract and release verdict | `WIRED` | yes |
| REVIEW & REPAIR | targeted repair planning | `WIRED` | yes |
| REVIEW & REPAIR | automated commercial reviewer | `NOT_WIRED` | no |
| REVIEW & REPAIR | prospective intervention ledger | `WIRED` | yes |

**Nine capabilities are `WIRED`. Fifteen are not.** That ratio is the honest state of
the system, and it is the reason a Third SKU blind run is still a test of the
capabilities that *are* wired rather than of a finished pipeline.

## Read this before claiming one-command production

The fast path is an authoritative **control** path, not an autonomous editor. It knows
which stage comes next and which capability must run. It does **not**:

- resolve `REVIEW_REQUIRED` or `SUPERVISOR_DECISION_REQUIRED` — both always stop the run
- repair anything on its own
- render video, mix audio, or package a delivery

`ASSEMBLE & MASTER` returns `SUPERVISOR_DECISION_REQUIRED` and never `PASS`, because
there is no packaging code in this repository. A run that reaches it has stopped, not
finished.

## Known limitations carried in this manifest

- **DaVinci.** Not globally classified as unable to render. Resolve rendered five full
  timelines on 2026-09-15/16 with passing pixel validation. The recorded failure is
  specifically a **Fusion Text+ title bake** under the recorded environment, never
  diagnosed and never re-tested. Out of scope; not investigated.
- **Typography.** The historical SKU#1 `editorial_text_plan.json` is rejected by the
  frozen policy validator for nine unrelated extra keys, and the policy vocabulary can
  express 3 of its 5 events. Recorded, deliberately not repaired.
- **Selected-range verification.** The project's own note stands: *"no automated check —
  needs vision."*
- **Run-aware segmentation.** Unresolved (C-01); the VFR *execution* aspect is what this
  commit addresses.
- **Semantic grouping.** Structurally inert in the only run that reached it:
  `group_shapes` was `{SINGLE: 18}` because the caller passed a constant
  `narrative_role`, so no `ACTION_RESULT` unit was ever produced.

## Intervention baseline

The Second SKU baseline is frozen at **`PARTIALLY_VERIFIED`** in
[`sku2-intervention-baseline.json`](sku2-intervention-baseline.json), with a confidence
label on every field. Four values are `PARTIAL` and two are `NOT_VERIFIABLE`. Nothing in
this repository reconstructs, infers, or upgrades them.

A Third SKU records interventions prospectively through
`src/ai_autocut/intervention_ledger.py`, appended at the moment they occur. Comparison
is a key-by-key subtraction against the frozen baseline, and a delta against a
`NOT_VERIFIABLE` field is reported as trend context, never as measured improvement.
