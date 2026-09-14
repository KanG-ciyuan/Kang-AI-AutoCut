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

New contracts live in this directory until they earn the same treatment.

## Implementation status is part of the contract

Several documents here are policy that is validated while its implementation is
still pending. That distinction is recorded in the schema (`policy_status`,
`implementation`, `compiler_status`) and asserted by tests, so a validated
policy is never mistaken for a shipped feature.
