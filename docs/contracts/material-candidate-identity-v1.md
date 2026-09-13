# Material / Candidate Identity v1 Contract

- **Catalog schema:** `material_candidate_identity.v1`
- **Locator schema:** `material_locations.v1`
- **Implementation:** `src/ai_autocut/identity.py`
- **Canonical catalog fixture:** `tests/fixtures/material_candidate_identity_v1_valid.json`
- **Status: frozen**

## Purpose and boundary

This contract gives AI-AutoCut stable, deterministic names for an exact local
video file and for an exact frame interval within one of its video streams. It
does not provide media discovery, semantic matching, ranking, approval,
provenance, storage, synchronization, or a media-management platform.

A Material is one exact byte sequence registered as a video asset. A Candidate
is one immutable interval in one video stream of one Material. A Candidate is
not a timeline Segment: the same Candidate may be used by more than one Segment.

## Material identity

The complete file is hashed with SHA-256, without a cache or partial-hash fast
path:

```text
material_id = "matv1_" + sha256(exact_file_bytes)
```

Path, filename, extension, directory, mtime, inode, and discovery order do not
participate in identity. Moving, renaming, or copying byte-identical content
does not change `material_id`. Any byte change creates a new Material in v1,
including a remux, re-encode, or metadata rewrite.

Each Material record has exactly:

| Field | Type | Rule |
| --- | --- | --- |
| `material_id` | string | `matv1_` plus the lowercase full SHA-256 |
| `content_sha256` | string | Lowercase 64-character SHA-256 of exact bytes |
| `byte_size` | integer | Non-negative file size, used as an audit check, not identity |
| `media_kind` | string | Exactly `video` in v1 |

## Candidate identity

The only Candidate identity fields are:

- `material_id`
- `stream_index`
- `start_frame`
- `end_frame_exclusive`

They are encoded as UTF-8 JSON with lexicographically sorted keys and separators
`,` and `:` with no extra whitespace. The Candidate ID is:

```text
candidate_id = "candv1_" + sha256(
  utf8("ai-autocut:candidate:v1\n") + utf8(canonical_identity_json)
)
```

`stream_index`, `start_frame`, and `end_frame_exclusive` are non-negative
integers; booleans and floats are rejected. The source interval uses canonical
end-exclusive semantics: `[start_frame, end_frame_exclusive)`, and the end must
be greater than the start.

Changing any identity field creates a new Candidate ID. Identity is not path,
score, label, description, analysis evidence, approval, selection state,
continuation group, Agent identity, or timestamp. Those values must not be
added to a Candidate identity record.

## Path-free shared catalog

The catalog is a JSON object with exactly `schema_version`, `materials`, and
`candidates`. Material and Candidate records accept exactly the fields above.
Unknown fields are contract errors. Material IDs and Candidate IDs must each be
unique, supplied IDs must match their canonical derivation, and every Candidate
must reference a Material present in the same catalog.

The catalog contains no path or filename field. Its deterministic rendering
sorts object keys, Materials by `material_id`, Candidates by `candidate_id`,
uses a two-space indent, and ends with one newline.

## Machine-local locator

`material_locations.v1` is deliberately separate from shared identity. It has
exactly `schema_version` and `locations`; each location has exactly one
`material_id` and a non-empty `paths` array. Duplicate Material entries and
duplicate paths are errors.

Resolution never trusts a path alone. Every existing located file is completely
rehashed and checked against both the registered SHA-256 and byte size. A
missing Material, absent locator, no existing file, unreadable file, or hash or
size mismatch fails closed. Error messages do not echo local paths.

Locator documents belong in task-local runtime data outside Git. They must not
be embedded into the shared Identity Catalog, Boundary Preflight reports, or
cross-machine audit artifacts.

## Boundary Preflight v1 binding

This contract is upstream of the frozen `boundary_preflight.v1`; it neither
changes that schema nor creates v2. Before binding, the caller validates that:

1. the Material exists in the Identity Catalog;
2. the Candidate exists and belongs to that Material;
3. the Segment source range exactly equals the Candidate interval; and
4. before media execution, the Material locator resolves with a fresh full-file
   SHA-256 verification.

The adapter then emits the existing preflight fields:

```text
source_id = material_id
candidate_id = candidate_id
source_range = {
  start_frame: candidate.start_frame,
  end_frame_exclusive: candidate.end_frame_exclusive
}
```

`segment_id` remains the identity of one Editing Plan placement.
`continuation_group` remains relationship evidence and is not Candidate identity.
The generated document is validated by the existing Boundary Preflight v1
parser before it is returned.

## Compatibility rule

Version 1 is closed. Adding, removing, renaming, or changing the meaning or type
of catalog identity fields requires a separately reviewed schema version. Local
locator values may change without changing Material or Candidate identity, but
the `material_locations.v1` document shape is also frozen.

The implementation intentionally adds no database, hash cache, media probe,
semantic or perceptual deduplication, ranking, UI, cloud service, provider, or
paid API.
