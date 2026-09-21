# Hook Decision v1 Contract

- **Schema:** `hook_decision.v1`
- **Implementation:** `src/ai_autocut/creative_intent.py`
- **Canonical fixture:** `tests/fixtures/hook_decision_v1_valid.json`
- **Canonical workspace path:** `planning/hook_decision.json`
- **Status:** contract implemented and tested, and **produced by one stage**:
  `DECIDE THE HOOK` (`src/ai_autocut/hook_planning.py`).

## WHAT PRODUCES A DECISION, AND WHAT STILL DOES NOT

The contract is produced by `run_hook_planning_stage`, which makes **one** creative
model call per run, through the existing authoring seam, and then applies a
deterministic veto. The model owns the creative ranking and the stage never
re-ranks it. There are exactly three outcomes:

| Outcome | Recorded as |
| --- | --- |
| `SELECTED` | exactly one hypothesis is eligible: it is selected, and `decision_owner` is assigned |
| `PENDING` | **several** hypotheses are eligible: `selected_hook_id: null` with `decision_owner: UNASSIGNED`, because the gate may not rank creative options |
| `INSUFFICIENT` | **no** hypothesis is eligible: every hypothesis carries a rejection code and the owner is assigned |

The gate never invents a rejection reason. It does not compare evidence strength
between hypotheses, does not score them, and does not reorder them; a viable
hypothesis that the model ranked below another is not "weaker evidence", it is
simply not the one the owner has chosen yet. No case calls a second model.

**Where the model's ordering lives.** The order the model returned is preserved in
`planning/hook_planning_response.json`. It is *not* recorded in the decision:
`hook_decision.v1` sorts hypotheses by `hook_id`, so the decision document is a set
with assessments, not a ranking.

**What the fact gate can and cannot prove.** The deterministic gate enforces
**declared Product Fact reference validation**: every `product_fact_refs` entry a
hypothesis declares must be inside the Claim Envelope. It cannot prove that a
premise declared *every* fact it implicitly rests on, because that would mean
parsing commercial prose. Completeness therefore rests on the bounded prompt, the
Claim Envelope, and producer review - not on the gate.

What the stage does not do, and this contract still does not describe: shot
ordering, Timeline, Trim, Sequence Planning, voice-over or subtitle text, final
call to action, typography, audio, rendering, QA, release, A/B testing, or any
conversion prediction. `copy_direction` is a direction, never the finished line.
Hook scoring, Hook weights, and advertising knowledge graphs remain out of scope:
eligibility is a factual veto, not a score.

`hook_decision.v1` is not a Hook Generator, and a Hook Decision is not an Editing
Plan. Nothing downstream consumes one yet.

## Purpose and boundary

A hook is a commercial premise for the first seconds of a piece. Choosing one is
a creative act, and this contract does not perform it. It defines the document a
human or a supervisor Agent must produce when they do, so that the choice can be
reviewed.

The contract exists because "the AI picked an opening" is not reviewable. Every
hypothesis must state a finite Hook type, the premise in words, the evidence it
requires, the visual support it actually has, and an assessment that says whether
the premise is fact-safe and whether the footage can carry it. A rejection is a
code from a closed vocabulary, not a paragraph.

It is not a copywriting system, a scoring model, a brief authoring format, an
Editing Plan, or a Planning Evidence record.

## Data model

```json
{
  "schema_version": "hook_decision.v1",
  "candidate_evidence": { "ref": "analysis/candidate_evidence.json", "sha256": "<64 hex>" },
  "brief": { "ref": "brief/brief.json", "sha256": "<64 hex>" },
  "hypotheses": [ /* 2 to 5 HookHypothesis objects */ ],
  "selected_hook_id": "hookv1_<sha256> or null",
  "selection_reason_codes": [],
  "decision_owner": "UNASSIGNED"
}
```

Every object has an exact key set. A document has between 2 and 5 hypotheses: an
exploration of one option is not a decision, and a list of six is a brainstorm.

A hypothesis has exactly `hook_id`, `hook_type`, `commercial_premise`,
`required_evidence`, `available_visual_support`, `copy_direction`,
`expected_opening_structure`, and `assessment`. `assessment` has exactly
`fact_safety`, `evidence_coverage`, and `rejection_codes`.

`copy_direction` and `expected_opening_structure` are directions, not copy: they
describe the intent of the opening, and no finished copy is written by this
contract.

## Hook vocabulary

Five values, and no free text:

| `hook_type` | Opening claim shape |
| --- | --- |
| `PAIN` | the problem the product addresses |
| `OLD_WAY` | what the viewer does now instead |
| `RESULT` | the outcome, shown first |
| `CURIOSITY` | an open question the footage answers |
| `PRODUCT_DIRECT` | the product itself, named immediately |

## Hook identity

`hook_id` is content-addressed:

```text
hook_id = "hookv1_" + sha256(
  utf8("ai-autocut:hook:v1\\n") + utf8(canonical_json({
    "commercial_premise": "...", "hook_type": "..."
  }))
)
```

Two hypotheses with the same type and premise are the same hook, so they collide
and the document fails closed as a duplicate. Copy direction and expected opening
structure are downstream styling and do not participate in identity.

## Reason vocabularies

Rejection and selection reasons are disjoint closed sets. A code from the wrong
set is a contract error, so a rejection can never be recorded as a reason for
choosing.

| `rejection_codes` | Meaning |
| --- | --- |
| `UNSUPPORTED_CLAIM` | the premise asserts something the facts do not allow |
| `NO_OPENING_VISUAL` | there is no footage to open on |
| `INSUFFICIENT_EVIDENCE` | the footage cannot carry the premise |
| `DUPLICATES_SELECTED_PREMISE` | it restates the premise already chosen |
| `WEAKER_EVIDENCE` | a viable premise with weaker support than the selection |
| `FACT_UNSAFE_PREMISE` | the premise is known to be fact-unsafe |

| `selection_reason_codes` | Meaning |
| --- | --- |
| `FACT_SAFE` | the premise is permitted by the facts |
| `DIRECT_VISUAL_SUPPORT` | the footage shows it rather than merely allowing it |
| `BRIEF_ALIGNED` | it matches the brief's intended opening |
| `STRONGER_EVIDENCE` | its support is stronger than the alternatives' |

## Selection rules

- A selected hypothesis must be `FACT_SAFE`, must not be `INSUFFICIENT` on
  evidence coverage, must carry no rejection code, and requires an assigned
  `decision_owner` plus at least one selection reason code.
- Every hypothesis the decision did not select must carry a rejection code, *unless*
  the decision is pending: with no selection at all, an eligible hypothesis carries no
  code, because "viable but not chosen yet" is exactly what pending means.
- Any hypothesis sharing the selected Hook type must be rejected specifically as
  `DUPLICATES_SELECTED_PREMISE`.
- `selected_hook_id: null` with `decision_owner: "UNASSIGNED"` is a valid
  *pending* state: the hypotheses were assessed and nobody has decided yet. With
  an assigned owner, a null selection means every hypothesis was rejected.
- `assessment.fact_safety` other than `FACT_SAFE` requires a rejection code, and
  `FACT_UNSAFE` specifically requires `UNSUPPORTED_CLAIM`.

## Required evidence and visual support

Each hypothesis states the evidence dimensions it needs, using the shared
coverage tokens of `planning_evidence.v1` (`PRODUCT_VISIBLE`, `ACTION_ONSET`,
`OBSERVABLE_RESULT`, `BEFORE_STATE`, `AFTER_STATE`, `USAGE_CONTEXT`,
`CLAIM_SUPPORT_DIRECT`, `IDENTITY_SHOT`, `BODY_AREA`).

Each declared support item names a Candidate, one of those tokens, and a support
class from Candidate Evidence (`DIRECT`, `CONTEXTUAL`, `INFERRED`). Support must
answer a stated requirement, and a hypothesis with no visual support must say so
with `NO_OPENING_VISUAL`. `evidence_coverage: "FULL"` requires support for every
stated requirement.

### Direct support is checked, not trusted

`validate_hook_decision_against_evidence(decision, evidence, pool, catalog)` is
the anti-fabrication gate. It requires the declared `candidate_evidence`
reference to match the supplied bytes, requires the Pool to validate against the
identity catalogue, requires every Candidate offered as support to be an analysed
Pool member, and then checks the claim itself: a `DIRECT` support item is accepted
only when that Candidate's **structured** evidence actually records the dimension.

The evidence may be a `candidate_evidence.v1` or a `candidate_evidence.v2`
document, or an already-parsed one of either. Both are read through one reader and
answered through the authoritative view, so a claim can never be satisfied by a
prose field at either version.

| Token | Recorded in Candidate Evidence as |
| --- | --- |
| `PRODUCT_VISIBLE` | `product_visibility` of `PARTIAL`, `CLEAR`, or `HERO` |
| `IDENTITY_SHOT` | `product_visibility` of `HERO` |
| `ACTION_ONSET` | `action_presence` of `ACTION_PRESENT`, or in v1 a non-empty `action_evidence` |
| `OBSERVABLE_RESULT` | v1: action evidence plus a stated `visible_result`; v2: `ACTION_PRESENT` plus a structured result observation |
| `BEFORE_STATE` | `usage_context` of `PRE_USE` |
| `AFTER_STATE` | `usage_context` of `POST_USE` |
| `USAGE_CONTEXT` | any `usage_context` other than `UNKNOWN` |
| `BODY_AREA` | a `body_area` other than `UNKNOWN` or `NOT_APPLICABLE` |
| `CLAIM_SUPPORT_DIRECT` | at least one claim with `DIRECT` support |

### Historical semantics are preserved; Phase 3 is stricter

The `OBSERVABLE_RESULT` row above is deliberately two rules, and the difference is a
scope decision rather than a contract change:

- **This validator keeps the v1 rule.** A v1 artifact that was directly supported
  before Phase 3 is still directly supported, `visible_result` prose included. Nothing
  that was legal became illegal because a new phase appeared.
- **The Phase 3 Hook gate is stricter, and only for the hooks it produces.** RESULT
  eligibility there requires a structured result observation, because "the footage
  shows the change" and "someone described the change" are different claims. That rule
  lives in `hook_planning`, never in this contract's validator.

So the stricter policy applies to new decisions, not retroactively to old evidence.
`validate_hook_decision_against_evidence` is never narrower than it was: on a v1
document its structured half is always false.

## References

Both `candidate_evidence` and `brief` are `{"ref", "sha256"}` pairs using the
repository's existing artifact reference convention: a workspace-relative logical
path ending in `.json`, plus the SHA-256 of the exact bytes. No URI scheme is
introduced.

The canonical fixture is chained: `tests/fixtures/hook_decision_v1_valid.json`
carries the exact SHA-256 of `tests/fixtures/candidate_evidence_v1_valid.json`,
so regenerating one requires regenerating the other.

The Candidate Evidence reference is verifiable in this phase, because that
document exists:
`validate_hook_decision_reference(decision, candidate_evidence_text)` fails
closed on stale or mismatched bytes. The reference binds the bytes of the evidence
**in the version it was supplied under**: a v1 document binds v1 bytes, so a frozen
v1 decision stays verifiable instead of being re-bound to a v2 rendering nobody
wrote.

The brief reference is now checked too. `validate_brief_binding(decision,
brief_text)` fails closed when the brief has changed since the decision was made,
which is what makes "this decision was made against that brief" a checkable
statement rather than a comment.

## Serialization

Sorted object keys, two-space indentation, one trailing newline. Hypotheses are
sorted by `hook_id`; requirements by coverage token; support by token then
Candidate; reason codes by value. The same structured input renders
byte-identical output regardless of input order.

## Failure behaviour

Every violation raises a contract error. Nothing is repaired or partially
accepted, and no error message echoes the offending value.

A hypothesis the gate vetoes is still recorded, with the most serious cause as its
rejection and every code the contract requires alongside it: an insufficient
coverage always carries `INSUFFICIENT_EVIDENCE`, an unsafe premise always carries
`UNSUPPORTED_CLAIM`, and a hypothesis left with no validated support always carries
`NO_OPENING_VISUAL`. A reviewer therefore never has to read a defect as a crash: a
fabricated `candidate_id`, for instance, loses that hypothesis rather than the run.

## Compatibility rule

Version 1 is closed. New Hook types, new reason codes, or any key change require
a separately reviewed version. The producing stage adds no scoring, no Hook
taxonomy beyond the five frozen types, no per-SKU rules, no second model, and no
change to the Copy System or to Candidate Evidence.
