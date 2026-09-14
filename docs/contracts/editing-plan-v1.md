# Editing Plan v1 Contract

- **Schema:** `editing_plan.v1`
- **Implementation:** `src/ai_autocut/editing_plan.py`
- **Canonical fixture:** `tests/fixtures/editing_plan_v1_valid.json`
- **Status:** frozen on implementation

## Purpose and boundary

An Editing Plan is one immutable, content-addressed choice of complete
Candidates from a declared Candidate Pool, in the order that forms one
contiguous linear preview timeline. It records the editing decision only.

It is not Candidate selection, source identity, boundary approval, an NLE
timeline, execution instruction set, Planning Evidence record, or media
management system.

## Data model

```json
{
  "schema_version": "editing_plan.v1",
  "plan_id": "planv1_<sha256>",
  "candidate_pool_id": "poolv1_<sha256>",
  "segments": [
    { "candidate_id": "candv1_<sha256>" }
  ]
}
```

The document has exactly `schema_version`, `plan_id`, `candidate_pool_id`, and
`segments`. A Segment has exactly `candidate_id`. Segments are non-empty and
ordered; duplicate Candidate use is allowed. Unknown or missing keys are
contract errors.

A Segment realizes the complete Candidate interval. It never repeats a source
range, Material ID, stream index, trim range, local path, filename, score,
reason, explanation, confidence, model, label, or analysis state. A shorter
interval must first be created as a distinct Candidate Identity upstream.

## Plan identity and serialization

The plan identity payload is UTF-8 canonical JSON of exactly:

```text
{
  "candidate_pool_id": "...",
  "segments": [{"candidate_id":"..."}, ...]
}
```

Object keys are lexicographically sorted, separators are `,` and `:`, and
Segment array order is preserved. The ID is:

```text
plan_id = "planv1_" + sha256(
  utf8("ai-autocut:editing-plan:v1\\n") + utf8(canonical_plan_identity_json)
)
```

Changing the Pool, Candidate, ordered sequence, or Segment count changes the
Plan ID. Agent identity, timestamp, path, filename, reason, score, confidence,
model, label, explanation, and external planning evidence do not participate.
Rendered documents use sorted object keys, two-space indentation, and exactly
one trailing newline.

## Linear timeline and derived Segment IDs

The first resolved Candidate starts at relative frame `0`. Each next Candidate
starts at the sum of all preceding resolved Candidate durations. Gaps,
overlaps, tracks, and explicit record placement fields are not supported.

Plan Segment IDs are not stored. The adapter derives `segv1_000001`,
`segv1_000002`, and so on from one-based ordered position when the existing
Boundary Preflight binding requires them.

## Candidate Pool and Identity validation

Before consumption, the caller validates the supplied Pool, requires
`plan.candidate_pool_id == pool.pool_id`, and validates every Segment Candidate
against that Pool and the supplied Identity Catalog. Any malformed, unknown,
Pool-mismatched, or Pool-external Candidate fails closed.

Identity Catalog remains the sole source for Material, stream, exact source
range, and Candidate duration.

## Boundary Preflight relation

The adapter validates Plan → Pool → Identity, derives Segment IDs and contiguous
relative placement, then calls the existing Identity binding. It emits the
unchanged `boundary_preflight.v1` schema. Boundary safety evidence and planning
explanations are outside this contract.

## Compatibility rule

Version 1 is closed. Field changes require a separately reviewed version. This
contract adds no execution adapter, database, registry, UI, ranking, Planning
Evidence schema, provider, or paid API.
