# Planning Evidence v1 Contract

- **Schema:** `planning_evidence.v1`
- **Implementation:** `src/ai_autocut/editing_intelligence.py`
- **Canonical fixture:** `tests/fixtures/planning_evidence_v1_valid.json`
- **Canonical workspace path:** `planning/planning_evidence.json`
- **Status:** contract implemented and tested. **No Sequence Planner and no production wiring exist yet.**

## CONTRACT EXISTS, PRODUCTION CAPABILITY DOES NOT

This document defines a data contract. The contract exists, and vNext production
wiring does not yet exist: no Sequence Planner runs, no planner writes a
`planning_evidence.v1` document, and nothing in the production path reads one.
The only document that exists is a fixture.

The reason codes and coverage tokens defined here are the vocabulary a planner
will later have to speak. Defining the vocabulary is not implementing the
planner, and a future Agent must not read this file as evidence that automatic
planning exists.

## Purpose and boundary

`editing_plan.v1` records what was chosen, in what order. It deliberately records
no reason, and it must not start recording one - selection belongs to the Plan,
explanation belongs here.

Planning Evidence is the companion artifact that explains one Editing Plan:
which requirements the plan had to satisfy, what each considered Candidate
contributed, which Candidates were kept, trimmed, or rejected, and why. It is
attached to the Plan, never merged into it.

It is not a Sequence Planner, a scoring model, a timeline compiler, a renderer, a
review, or an approval.

## Data model

```json
{
  "schema_version": "planning_evidence.v1",
  "plan_id": "planv1_<sha256>",
  "hook_decision": { "ref": "planning/hook_decision.json", "sha256": "<64 hex>" },
  "requirements": ["PRODUCT_VISIBLE", "ACTION_ONSET"],
  "decisions": [ /* one PlannedCandidateDecision per considered Candidate */ ],
  "coverage_summary": {
    "covered_tokens": [],
    "missing_tokens": [],
    "redundant_keeps": 0,
    "decision_counts": { "KEEP": 0, "TRIM": 0, "REJECT": 0 }
  },
  "total_duration_frames": 0,
  "planner_run_id": "plannerrunv1_example"
}
```

Every object has an exact key set. `requirements` is non-empty: a plan that must
satisfy nothing cannot be evaluated.

A decision has exactly `candidate_id`, `decision`, `sequence_position`,
`adds_coverage`, `redundant_with`, `duration_cost_frames`, `reason_codes`, and
`why`.

## Machine truth versus prose

`why` is human-readable explanation. Every machine judgement reads `decision`,
`adds_coverage`, `redundant_with`, `duration_cost_frames`, and `reason_codes`.
No validator, planner, or reviewer may parse `why` to reconstruct a decision, and
rewriting it changes no machine outcome.

## Coverage tokens

Tokens are the currency between a requirement and the Candidate that satisfies
it. They are coarse on purpose: a token says which question a shot answers, not
what the shot looks like. The same vocabulary is used by the Hook Decision
contract to state required evidence.

| Token | The plan must contain footage that |
| --- | --- |
| `PRODUCT_VISIBLE` | shows the product itself |
| `ACTION_ONSET` | starts on an observable action |
| `OBSERVABLE_RESULT` | keeps the action's result on screen |
| `BEFORE_STATE` | shows the state before use |
| `AFTER_STATE` | shows the state after use |
| `USAGE_CONTEXT` | shows the product in use |
| `CLAIM_SUPPORT_DIRECT` | proves a commercial claim rather than asserting it |
| `IDENTITY_SHOT` | identifies the product unmistakably |
| `BODY_AREA` | shows the relevant part of the body |

A coverage token may be claimed by only one sequence position. A plan cannot
claim the same dimension twice, and it cannot claim coverage the requirements do
not ask for.

## Decisions

| `decision` | `sequence_position` | `duration_cost_frames` | Meaning |
| --- | --- | --- | --- |
| `KEEP` | required, 1..N | exactly the Candidate's identified duration | the complete Candidate is used at that position |
| `TRIM` | required, 1..N | positive and strictly less than the identified duration | the planned contribution is shorter than the identified interval |
| `REJECT` | `null` | `0` | the Candidate was considered and not used |

`TRIM` declares a shorter contribution. It does **not** authorize trimming inside
`editing_plan.v1`: the Plan still references complete Candidates, so a shorter
interval has to exist as a distinct Candidate Identity first. This contract
validates the declaration; it does not create the Candidate.

### Redundancy and reinforcement

A selected Candidate may be kept while being semantically redundant with an
earlier one, but only with an explicit reinforcement reason:

| Reason code | Meaning |
| --- | --- |
| `MULTI_AREA_REQUIREMENT` | the requirement spans more than one area or subject |
| `ACTION_TO_RESULT_RELATION` | it makes a cause-and-effect relation readable |
| `CONTRAST_OR_OLD_WAY` | it carries a contrast the plan needs |
| `HOOK_CALLBACK` | it answers the opening premise later |
| `RHYTHM_BRIDGE_WITH_NO_SEMANTIC_ALTERNATIVE` | pacing needs it and nothing else can carry that beat |
| `PRODUCER_EXPLICIT_REINFORCEMENT` | a Producer asked for the repetition |

A redundant decision must not also claim new coverage, must name a *selected*
Candidate at an **earlier** sequence position, and may use only the codes above.
A non-redundant selection must claim coverage and may not use a withholding code
as a justification for keeping something.

### Withholding reasons

| Reason code | Meaning |
| --- | --- |
| `SEMANTIC_SATURATION` | the dimension is already carried by the plan |
| `NO_NEW_EVIDENCE_DIMENSION` | it adds no dimension the plan lacks |
| `ANALYSIS_UNAVAILABLE` | no analysis exists for it, so it cannot be judged |

`FIRST_DIRECT_PROOF` is the coverage-add code: this position is where the
dimension is first proven directly.

Only `SEMANTIC_SATURATION`, `NO_NEW_EVIDENCE_DIMENSION`, and
`ANALYSIS_UNAVAILABLE` may justify a `REJECT`. `ANALYSIS_UNAVAILABLE` is the one
addition to the vocabulary given in the implementation plan: the defined codes
describe coverage and redundancy only, and none of them can express "the
Candidate could not be analysed, so it could not be considered". Without it, an
unanalysable Candidate could only be dropped silently, which is the failure the
Candidate Evidence cardinality rule exists to prevent.

## Coverage consistency

`coverage_summary` is not a place to make claims; it is derived. It fails closed
unless:

- `covered_tokens` is exactly the union of the `adds_coverage` claims;
- `missing_tokens` is exactly the requirements that are not covered;
- `covered_tokens` and `missing_tokens` do not intersect, and covered tokens are
  a subset of the requirements;
- `decision_counts` and `redundant_keeps` match the decisions exactly;
- `total_duration_frames` equals the sum of the selected duration costs.

A missing dimension is reported honestly in `missing_tokens`. It is not hidden by
declaring it covered.

## Plan binding

`validate_planning_evidence_binding(evidence, plan, pool, catalog)` requires:

- `plan_id` to match the supplied Plan;
- every considered Candidate to be a member of the supplied Pool and Identity
  Catalog;
- the selected sequence positions to be exactly `1..N` and to map one-to-one, in
  order, onto the Plan's segments;
- a `KEEP` to spend exactly the Candidate's identified duration, and a `TRIM` to
  spend less;
- no `REJECT` decision to name a Candidate that appears in the Plan.

## References

The canonical fixture is chained: `tests/fixtures/planning_evidence_v1_valid.json`
carries the exact SHA-256 of `tests/fixtures/hook_decision_v1_valid.json`, which
in turn carries the hash of the Candidate Evidence fixture. Regenerating them out
of order produces a stale reference that the validator rejects.

`hook_decision` is a `{"ref", "sha256"}` pair using the repository's existing
artifact reference convention - a workspace-relative logical path ending in
`.json`, plus the SHA-256 of the exact bytes. No URI scheme is introduced.
`validate_planning_evidence_reference(evidence, hook_decision_text)` fails closed
when the referenced Hook Decision is a different revision from the one the plan
was explained against.

## Serialization

Sorted object keys, two-space indentation, one trailing newline. Decisions are
sorted by `candidate_id` (the sequence position is an explicit field, so array
order carries no meaning); requirements, coverage tokens, reason codes, and
redundancy targets are sorted. The same structured input renders byte-identical
output.

## Failure behaviour

Every violation raises a contract error. Nothing is repaired or partially
accepted, and no error message echoes the offending value.

## Compatibility rule

Version 1 is closed. New tokens or reason codes require a separately reviewed
version. This contract adds no field to `candidate_pool.v1` or `editing_plan.v1`,
implements no planner, compiles no timeline, and renders nothing.
