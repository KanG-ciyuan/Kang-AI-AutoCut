# Candidate Evidence v2 Contract

- **Schema:** `candidate_evidence.v2`
- **Predecessor:** [`candidate_evidence.v1`](candidate-evidence-v1.md) — frozen, unchanged, still parsed
- **Implementation:** `src/ai_autocut/candidate_evidence_v2.py`
- **Canonical workspace path:** `analysis/candidate_evidence.json` (the schema version names itself; v1 and v2 do not share a document)
- **Status:** contract implemented and tested; produced by the shadow stage under `candidate_evidence_prompt.v3`

## Why a successor version instead of a patch

Phase 2.5's live multimodal validation produced honest answers that v1 could not
hold. Two windows contained no action at all, and the only place to say so was the
free-text `visible_action` field: *"no action: the surface is static across every
sampled frame"*. The visible problem state of a surface — the thing a hook would
open on — had no home either, because the Claim Envelope deliberately carries no
hygiene fact, and adding one would have turned an observation into a commercial
claim.

`candidate_evidence.v1` states its own rule: *"Version 1 is closed. Adding,
removing, renaming, or changing any key or vocabulary member requires a separately
reviewed version."* The change needed therefore had to be a successor, not a
widening. This is a **semantic schema expansion** (option B in the Phase 2.6
brief), and it is classified as such — unlike the hyphen defect, which was an
implementation bug fixed in place.

## What v2 adds

Exactly two keys, both inside `observations`. The eleven entry keys are identical
to v1; only the observations object grows from seven keys to nine.

```json
"observations": {
  "visible_action": "...", "visible_result": null,
  "product_visibility": "PARTIAL", "usage_context": "IN_USE",
  "body_area": "HANDS", "visual_usability": "USABLE",
  "claim_support_class": "DIRECT_DEMONSTRATION",
  "action_presence": "ACTION_PRESENT",
  "observable_states": ["CONTACT_VISIBLE", "STATE_CHANGE_VISIBLE"]
}
```

### `action_presence`

| Value | Meaning |
| --- | --- |
| `ACTION_PRESENT` | an observable action happens within these frames |
| `NO_ACTION` | these frames positively show no action — a statement about the footage |
| `NOT_RECORDED` | the analyzer did not judge it — a statement about the analysis |

Absence becomes a statement instead of a silence, and "nobody said" stays
distinguishable from "there was nothing to see".

### `observable_states`

| Code | Meaning |
| --- | --- |
| `PROBLEM_STATE_VISIBLE` | the subject is visibly in the adverse or soiled state the piece addresses |
| `CLEAN_STATE_VISIBLE` | the subject is visibly in the cleared or restored state |
| `STATE_CHANGE_VISIBLE` | the visible state of the subject changes within these frames |
| `BEFORE_AFTER_RELATION_VISIBLE` | both the before and the after state, and their relation, are visible |
| `CONTACT_VISIBLE` | an implement or body part is visibly in contact with the subject |
| `FLOW_VISIBLE` | a liquid is visibly moving over the subject |
| `PRODUCT_IDENTITY_VISIBLE` | the product itself is visibly identifiable in these frames |
| `PRODUCT_BEAUTY_STATE_VISIBLE` | the product is presented in a beauty or hero state; this asserts no effect |
| `HUMAN_USE_VISIBLE` | a person is visibly handling or using the product or subject |

Every member is a statement about what is *visible*. None is a claim about effect,
and a test asserts that no code or definition contains efficacy language.

## Cross-field rules

1. `ACTION_PRESENT` requires the action evidence that shows it.
2. `NO_ACTION` may not contradict recorded action evidence.
3. An event observation (`CONTACT_VISIBLE`, `FLOW_VISIBLE`, `STATE_CHANGE_VISIBLE`,
   `BEFORE_AFTER_RELATION_VISIBLE`) requires `ACTION_PRESENT`.
4. `PRODUCT_IDENTITY_VISIBLE` and `PRODUCT_BEAUTY_STATE_VISIBLE` require the product
   to be visibly present (`product_visibility` is not `NOT_VISIBLE`).
5. States are unique and canonically ordered; a non-`ANALYZED` entry carries no
   observations at all.

Everything else is inherited unchanged: status matrix, confidence bounds,
frame-exact provenance, action chronology inside cited provenance, DIRECT proof
obligations, and the Product Fact allow-list. A v2 entry is built *through* the v1
parser and then wrapped, so v1's rules are enforced by v1 rather than restated.

## Observations are not claims

A structured observation can never become claim support:

- the vocabulary contains no effect code, so there is no way to say "cleans well";
- nothing in the module derives a claim from a state — claims exist only where the
  analyzer asserted one against a fact the Claim Envelope permits;
- a claim against an unpermitted fact is still refused with the analysis recorded as
  `ANALYSIS_FAILED`.

A beauty shot may therefore be `PRODUCT_BEAUTY_STATE_VISIBLE` and carry no efficacy
truth at all. This is asserted by test, including the adversarial case.

## Machine truth versus explanatory text

| Class | Fields | A consumer may |
| --- | --- | --- |
| **Authoritative** | `candidate_id`, `status`, `action_presence`, `observable_states`, `claims` (fact + support + provenance), `provenance`, `action_evidence`, `confidence`, `evidence_type`, `product_visibility`, `usage_context`, `body_area`, `visual_usability`, `risk_codes` | branch on these |
| **Non-authoritative prose** | `rationale`, `observations.visible_action`, `observations.visible_result`, `claims[].note`, `risks[].note` | read them as explanation only |

`rationale` is `NON_AUTHORITATIVE_EXPLANATORY_TEXT`. Phase 2.5 showed that
claim-like marketing language can sit in a `rationale` with no envelope checking it,
so prose may explain a structured decision but may never create one. No consumer may
parse it for claims, coverage, hook requirements, or Product Facts.

`authoritative_evidence_view(evidence)` returns the machine-truth view and has **no
prose field by construction**, so a planner cannot read prose even by accident. A
test mutates every prose field into marketing language and asserts the view is
byte-identical.

## Evidence truth is a separate axis

Contract validity and evidence truth answer different questions:

| | Question | Decided by |
| --- | --- | --- |
| **Contract safety** | is the document well formed, are the facts permitted, are the coordinates real? | `validate_candidate_evidence_v2` (and v1 beneath it) |
| **Evidence truth** | does the media actually show what a `DIRECT` claim asserts? | `audit_frame_provenance` + `declared_check_status` |

`CONTRACT_VALID = YES` with `DECLARED_CHECK_STATUS = CHECKS_FAILED` is a representable,
normal outcome. Phase 2.6 demonstrated it: a beauty bank asserting a surface state change
passes every contract rule — the fact is permitted and the frames exist — and fails a
declared `STABLE` check that measures the media.

The audit keeps its three questions (image integrity, coordinate honesty, and the
substance of each declared expectation) and now reports a status:

| Status | Meaning |
| --- | --- |
| `CHECKS_PASSED` | every `DIRECT` assertion is covered by a declared check that measured its own predicate and passed |
| `CHECKS_FAILED` | integrity, bounds, cited-frame, or a declared check failed |
| `NOT_VERIFIED` | nothing failed, and at least one `DIRECT` assertion has no declared check |

`NOT_VERIFIED` is the honest default for an unmeasured assertion. Deterministic
measurement is not available for every visual predicate — "a surface is visible" and
"an implement is in contact" have no cheap pixel test — and this contract does not
pretend otherwise.

**Scope of a pass.** `CHECKS_PASSED` is a statement about declared pixel predicates,
not about meaning: the check names a region and a threshold, and a hand-picked region
can encode the expected answer. Nothing here proves a commercial assertion, and
nothing here should be reported as "verified" in a wider sense. Frame evidence itself
is produced by the opt-in live-validation harness; the shadow analysis stage neither
requires nor parses it, so a document can be contract-valid without any frame
manifest at all.

## Reading both versions

```text
read_candidate_evidence(document) -> CandidateEvidenceV2
```

One read path for consumers. A v2 document parses directly; a v1 document is
migrated. Migration is lossless for everything v1 could express and explicit about
everything it could not:

- `observable_states` becomes `[]` — "no structured observation was recorded";
- `action_presence` is derived only from recorded action evidence:
  `ACTION_PRESENT` when evidence exists, `NOT_RECORDED` otherwise;
- a v1 entry that says "no action" in prose migrates to `NOT_RECORDED`, never to
  `NO_ACTION`. Prose is not machine truth and migration may not upgrade it.

The v1 parser and validator are unchanged, so v1 documents and their fixtures keep
working. V01–V05 and every accepted production record are untouched: nothing here
rewrites a document that already exists.

## Compatibility rule

Version 2 is closed in the same way version 1 is. Adding a state code, changing a
meaning, or altering the key set requires a separately reviewed version. Version 1
remains authoritative for every v1 document ever produced.
