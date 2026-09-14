# Candidate Pool v1 Contract

- **Schema:** `candidate_pool.v1`
- **Implementation:** `src/ai_autocut/candidate_pool.py`
- **Canonical fixture:** `tests/fixtures/candidate_pool_v1_valid.json`
- **Status:** frozen on implementation

## Purpose and boundary

A Candidate Pool is one immutable, content-addressed snapshot of the existing
Candidate Identity records that Planning may use for one editing task. It
answers membership only: whether an existing Candidate belongs to this
snapshot.

It is not a material-management platform, registry service, analysis record,
ranking model, approval workflow, replacement graph, or Editing Plan.

## Data model

```json
{
  "schema_version": "candidate_pool.v1",
  "pool_id": "poolv1_<sha256>",
  "entries": [
    { "candidate_id": "candv1_<sha256>" }
  ]
}
```

The document has exactly `schema_version`, `pool_id`, and `entries`. Each
entry has exactly `candidate_id`. Unknown or missing keys are contract errors.
An empty `entries` array is valid and means Planning has no available Candidate
in this Pool.

`candidate_id` is the complete Candidate ID from the frozen
`material_candidate_identity.v1` catalog. It must be unique and must exist in
the supplied Identity Catalog. A Pool never repeats `material_id`, stream,
source range, path, filename, analysis, score, label, description, approval,
or selection state.

## Pool identity and serialization

Entries are sorted by full `candidate_id`. The canonical identity payload is
the UTF-8 JSON array of those sorted Candidate IDs, encoded with lexicographic
JSON ordering, `,` and `:` separators, and no extra whitespace:

```text
pool_id = "poolv1_" + sha256(
  utf8("ai-autocut:candidate-pool:v1\\n") + utf8(canonical_member_array_json)
)
```

Input order does not affect the Pool ID. The same member set has the same Pool
ID; adding, removing, or replacing a Candidate creates a different Pool ID.
Rendered documents use sorted object keys, two-space indentation, sorted
entries, and exactly one trailing newline.

## Mutability

The Pool is an immutable snapshot. Membership changes create a different Pool;
there is no revision system, status lifecycle, event log, `replaced_by`, or
provenance graph in v1. Candidate analysis or score changes do not alter a
Pool unless they cause its caller to create a new member set.

## Planning membership interface

The minimum interface is:

```text
validate_candidate_membership(candidate_pool_id, candidate_id, pool, catalog)
```

It validates the Pool ID and all Pool-to-Catalog references before returning the
existing Candidate Identity. A Candidate outside the Pool, a malformed Pool, or
an unknown Candidate fails closed.

Planning must use complete `candv1_<sha256>` values. Human labels such as
`C01` are not contract identifiers.

## Boundary Preflight relation

Pool membership is upstream of the existing Identity binding. It does not
change `boundary_preflight.v1`, add fields to it, or determine that a final
timeline cut is safe. A caller that has validated membership still uses the
existing Identity binding to emit `source_id`, `candidate_id`, and the exact
source range for Boundary Preflight v1.

## Compatibility rule

Version 1 is closed. Adding, removing, renaming, or changing any document or
entry field requires a separately reviewed version. This contract introduces no
database, media discovery, semantic search, UI, synchronization, provider, or
paid API.
