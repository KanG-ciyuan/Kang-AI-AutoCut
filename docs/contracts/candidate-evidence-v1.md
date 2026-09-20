# Candidate Evidence v1 Contract

- **Schema:** `candidate_evidence.v1`
- **Implementation:** `src/ai_autocut/candidate_evidence.py`
- **Canonical fixture:** `tests/fixtures/candidate_evidence_v1_valid.json`
- **Canonical workspace path:** `analysis/candidate_evidence.json`
- **Status:** contract implemented and tested. **No production writer exists yet.**

## CONTRACT EXISTS, PRODUCTION CAPABILITY DOES NOT

This document defines a data contract. In this phase the contract exists, and
vNext production wiring does not yet exist: nothing in the production path
writes, reads, enforces, or depends on a `candidate_evidence.v1` document. The
only documents that exist are fixtures, and the only semantic field values that
exist were written by hand inside those fixtures. No provider was called, no
frame was decoded, and no model produced any observation recorded here.

A future Agent must not read this file as evidence that semantic analysis is
available. `CONTRACT EXISTS` is not `CAPABILITY EXISTS`.

## Purpose and boundary

Candidate Evidence is the analysis companion to a Candidate Pool. `candidate_pool.v1`
answers membership and nothing else, so every observation about a Candidate -
what is visible, what result follows the action, whether the product is on
screen, which commercial claim those frames can carry - is recorded here instead
of being pushed into the Pool.

The contract exists to make one rule enforceable: **a claim may be judged, but it
may not be asserted without evidence.** A commercial claim must name a Product
Fact the document itself permits, `DIRECT` support must be bound to real frames
of the exact Candidate it names, and inference may not present itself as
something the camera proved.

It is not a media manager, a scoring model, a ranking, an approval workflow, an
Editing Plan, or a Planning Evidence record.

## Data model

```json
{
  "schema_version": "candidate_evidence.v1",
  "candidate_pool_id": "poolv1_<sha256>",
  "product_facts": {
    "ref": "brief/product_facts.json",
    "sha256": "<64 hex>",
    "allowed_fact_refs": ["fact_attaches_to_faucet_end"]
  },
  "analysis_run": {
    "run_id": "analysisrunv1_example",
    "provider": "example_provider",
    "model": "example_model_v1",
    "prompt_contract_version": "candidate_evidence_prompt.v1"
  },
  "entries": [ /* one CandidateEvidenceEntry per Pool member */ ]
}
```

Every object in this document has an exact key set. An unknown key, a missing
key, or a malformed value is a contract error, and the document is rejected
rather than partially consumed.

## Ownership: deterministic versus model-owned

| Field group | Owner | Enforced by this contract |
| --- | --- | --- |
| `schema_version`, `candidate_pool_id`, `product_facts`, `analysis_run` | Caller / identity chain | Shape, vocabulary, reference form, run metadata shape |
| `candidate_id`, `provenance`, `action_evidence` frames | Identity chain | Pool membership, exact Candidate range containment, chronology |
| `claims[].product_fact_ref` | Product Facts allow-list | Must be permitted by this document's own `allowed_fact_refs` |
| `claims[].support` | Model or human | Finite vocabulary; `DIRECT` carries provenance obligations |
| `observations`, `evidence_type`, `confidence`, `role_affinities`, `risks`, `rationale` | Model or human | Finite vocabulary, confidence bounds, cross-field consistency |

The right-hand column states what is *checked*. It does not state that anything
computes these values: in this phase a fixture supplies them.

### Entry shape

Each entry has exactly `candidate_id`, `status`, `observations`,
`action_evidence`, `claims`, `evidence_type`, `confidence`, `provenance`,
`role_affinities`, `risks`, and `rationale`. All eleven keys are always present.

`status` is `ANALYZED`, `ANALYSIS_FAILED`, or `UNKNOWN`:

- `ANALYZED` requires a non-null payload: `observations`, a non-empty
  `provenance`, `evidence_type`, `confidence`, and the (possibly empty)
  `action_evidence`, `claims`, `role_affinities`, and `risks` arrays.
- `ANALYSIS_FAILED` and `UNKNOWN` require every payload field to be `null`, and
  `rationale` must state why. A Candidate that was not analysed cannot smuggle in
  observations through a status field.

`rationale` is required in every status. It is human-readable: no validator,
planner, or reviewer may parse it to reconstruct a machine decision.

## Cardinality: no silent omission

For one Candidate Pool, every Pool member has **exactly one** entry, and no entry
may name a Candidate outside the Pool. A member that could not be analysed is
present with `ANALYSIS_FAILED` or `UNKNOWN`, not absent. Duplicate entries,
missing entries, and Pool-external entries all fail closed.

## Provenance semantics

`provenance` is a list of `{"start_frame", "end_frame_exclusive"}` ranges using
end-exclusive semantics, in absolute source frames of the named Candidate.

- An `ANALYZED` entry must cite at least one range.
- Every cited range, every `action_evidence` phase, and every claim provenance
  range must lie inside the Candidate's **exact identity range**. A frame outside
  that interval is not this Candidate's evidence.
- `action_evidence` records observable phases:
  `preparation_start <= action_onset <= action_completion < result_end_exclusive`.
  Actions must not overlap, and each action must lie inside the frames the entry
  cites - an action chronology cannot be recorded in frames the entry never
  claimed to have seen.
- `visible_result` must be stated when action evidence is present: an action cut
  that keeps no observable result is not evidence of anything.

### Claim support classes

| `support` | Meaning | Obligation |
| --- | --- | --- |
| `DIRECT` | the cited frames themselves show it | at least one provenance range, inside the Candidate's exact range |
| `CONTEXTUAL` | the cited frames are consistent with it | none beyond shape |
| `INFERRED` | it was concluded, not seen | none beyond shape |

`DIRECT` is the only class that may be described as visual proof, and it is the
only class with a frame obligation. `evidence_type: "NONE"` forbids `DIRECT`
support outright, and `observations.claim_support_class: "DIRECT_DEMONSTRATION"`
requires at least one `DIRECT` claim, so the summary class cannot outrun the
claims it summarises. `visual_usability: "UNUSABLE"` requires
`evidence_type: "NONE"`.

### Product Fact references

`claims[].product_fact_ref` is a logical fact token, and it must appear in
`product_facts.allowed_fact_refs` in the same document. A claim against a fact
the document does not permit - however plausible - fails closed. `product_facts`
also carries the logical `ref` and exact `sha256` of the artifact that states
those facts, using the repository's existing artifact reference convention.

## Identity

Candidate identity is not redefined here. `candidate_id` is the complete
`candv1_<sha256>` value from the frozen `material_candidate_identity.v1` catalog,
and the Pool is the frozen `candidate_pool.v1`. This contract never derives a
second Candidate identity, never accepts a human label such as `C01`, and never
trims a Candidate: a shorter interval must already exist as a distinct Candidate
Identity upstream.

## Serialization

Rendered documents use sorted object keys, two-space indentation, and exactly one
trailing newline. Entries are sorted by full `candidate_id`; provenance ranges,
claims, roles, and risks are sorted canonically; `allowed_fact_refs` is sorted.
The same structured input therefore renders byte-identical output, whatever order
the caller supplied it in.

`candidate_evidence_reference(evidence)` returns the `{"ref", "sha256"}` pair
that binds those exact rendered bytes, and
`validate_candidate_evidence_reference(evidence, text)` fails closed when the
bytes a consumer holds are a different revision. This is the reference form the
Hook Decision contract consumes.

## Failure behaviour

Every rejection is a raised contract error. Nothing is repaired, defaulted,
coerced, or partially accepted, and no error message echoes the offending value,
because a rejected value may be a machine path.

## Compatibility rule

Version 1 is closed. Adding, removing, renaming, or changing any key or
vocabulary member requires a separately reviewed version. This contract
introduces no provider client, media reader, vector store, database, GUI, or
paid API, and it adds no field to `candidate_pool.v1` or `editing_plan.v1`.
