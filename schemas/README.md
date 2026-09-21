# Schemas

Machine-readable contracts for AI-AutoCut knowledge that has been validated.

## Layout

```
schemas/
  README.md
  gold_manifest/      gold_manifest.v1  — validated, with one real record
  executable_timeline/executable_timeline.v0 — contract validated, compilers NOT_IMPLEMENTED
  audio_plan/         audio_plan.v0      — policy validated, synthesis NOT_IMPLEMENTED
  review/             review.v0          — contract validated
  typography/         typography_policy.v0 — policy validated, placement NOT_IMPLEMENTED
  candidate_shot/     candidate_shot.v0  — draft only, extraction NOT_IMPLEMENTED
```

Each directory holds a JSON Schema plus, where one exists, a real record that
the offline tests actually parse.

## Where the other contracts live

`candidate_pool.v1`, `editing_plan.v1`, `material_candidate_identity.v1`, and
`boundary_preflight.v1` are already frozen with a prose contract in
`docs/contracts/`, a validating implementation in `src/ai_autocut/`, and a
canonical fixture in `tests/fixtures/`. They are deliberately **not** duplicated
here: a second copy of a frozen contract is a second place for it to drift.

The Editing Intelligence vNext companion contracts — `candidate_evidence.v1`,
`hook_decision.v1`, and `planning_evidence.v1` — follow the same layout and are
likewise not duplicated here. `planning_evidence.v1` is still contract only: no
production path writes or reads it, so it documents a decided shape rather than a
shipped capability. `hook_decision.v1` now has a producer, and it runs in
`VNEXT_SHADOW` only, so the production path still neither writes nor reads it.

`candidate_evidence.v2` succeeded `candidate_evidence.v1` in Phase 2.6 to carry
structured visual observations. Version 1 is still parsed and validated, and is
described in `docs/contracts/candidate-evidence-v1.md`.

Candidate extraction and analysis add pipeline artifacts under the
`VNEXT_SHADOW` mode (`analysis/candidate_*.json`), described in
`docs/contracts/candidate-extraction-and-analysis-v1.md`. There is now an
implementation that produces `candidate_evidence.v1` from measured material in
shadow, and a `DECIDE THE HOOK` stage that turns that evidence, the Creative Brief
and the permitted Product Facts into `planning/hook_decision.json` - one creative
call, then a deterministic veto that selects only when exactly one hypothesis is
eligible and otherwise records a pending or insufficient decision. The production
fast path still neither writes nor requires any of them.

New contracts live in this directory until they earn the same treatment.

## Implementation status is part of the contract

Several documents here are policy that is validated while its implementation is
still pending. That distinction is recorded in the schema (`policy_status`,
`implementation`, `compiler_status`) and asserted by tests, so a validated
policy is never mistaken for a shipped feature.
