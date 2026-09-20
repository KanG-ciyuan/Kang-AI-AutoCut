# Hook Decision v1 Contract

- **Schema:** `hook_decision.v1`
- **Implementation:** `src/ai_autocut/creative_intent.py`
- **Canonical fixture:** `tests/fixtures/hook_decision_v1_valid.json`
- **Canonical workspace path:** `planning/hook_decision.json`
- **Status:** contract implemented and tested. **No generator, no selector, and no production wiring exist yet.**

## CONTRACT EXISTS, PRODUCTION CAPABILITY DOES NOT

This document defines a data contract. The contract exists, and vNext production
wiring does not yet exist: nothing generates a hook, scores a hook, selects a
hook, writes copy, or reads a `hook_decision.v1` document. The only document that
exists is a fixture, and the selection recorded in that fixture was written by
hand as test data. No model was called.

`hook_decision.v1` is not a Hook Generator. A future Agent must not read this
file as evidence that the system can choose an opening.

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
- Every hypothesis the decision did not select must carry a rejection code. An
  unselected option with no recorded reason is an incomplete decision.
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
reference to match the supplied bytes, requires every Candidate offered as
support to be an analysed Pool member, and then checks the claim itself: a
`DIRECT` support item is accepted only when the named Candidate Evidence entry
actually records that dimension.

| Token | Recorded in Candidate Evidence as |
| --- | --- |
| `PRODUCT_VISIBLE` | `product_visibility` of `PARTIAL`, `CLEAR`, or `HERO` |
| `IDENTITY_SHOT` | `product_visibility` of `HERO` |
| `ACTION_ONSET` | a non-empty `action_evidence` |
| `OBSERVABLE_RESULT` | action evidence plus a stated `visible_result` |
| `BEFORE_STATE` | `usage_context` of `PRE_USE` |
| `AFTER_STATE` | `usage_context` of `POST_USE` |
| `USAGE_CONTEXT` | any `usage_context` other than `UNKNOWN` |
| `BODY_AREA` | a `body_area` other than `UNKNOWN` or `NOT_APPLICABLE` |
| `CLAIM_SUPPORT_DIRECT` | at least one claim with `DIRECT` support |

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
closed on stale or mismatched bytes. The brief reference is **declarative only**
in this phase: the document is recorded, but no brief parser or hash check
exists yet, and that is recorded as an open item rather than implied to work.

## Serialization

Sorted object keys, two-space indentation, one trailing newline. Hypotheses are
sorted by `hook_id`; requirements by coverage token; support by token then
Candidate; reason codes by value. The same structured input renders
byte-identical output regardless of input order.

## Failure behaviour

Every violation raises a contract error. Nothing is repaired or partially
accepted, and no error message echoes the offending value.

## Compatibility rule

Version 1 is closed. New Hook types, new reason codes, or any key change require
a separately reviewed version. This contract introduces no provider call, no
generated hook, no selection logic, no copy generation, and no change to the Copy
System.
