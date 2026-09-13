# Boundary Preflight v1 Contract

- **Schema name / version:** `boundary_preflight.v1`
- **Implementation:** `src/ai_autocut/preflight.py` (offline JSON entry) delegating to `src/ai_autocut/boundary_guard.py`
- **Canonical example:** `tests/fixtures/boundary_preflight_v1_valid.json`
- **Status:** frozen. See [Compatibility rule](#compatibility-rule).

## Purpose

Describe one ordered sequence of timeline segments and ask a pure, offline
boundary guard whether every source out-point is safe, whether any adjacent
candidate boundary splits a continuous source, and whether the planned relative
placement matches contiguous timeline geometry.

The guard reports business risks as data. It performs no file, network, media,
editor, or process I/O beyond reading the single input document.

## Top-level fields

The document is a JSON object with exactly these keys. Any other key is a
contract error.

| Key | Required | Type | Meaning |
| --- | --- | --- | --- |
| `schema_version` | yes | string | Must be exactly `"boundary_preflight.v1"` |
| `segments` | yes | array | Non-empty, ordered by timeline order |

## Segment fields

Each element of `segments` is a JSON object with exactly these keys. Any other
key is a contract error.

| Key | Required | Type | Meaning |
| --- | --- | --- | --- |
| `segment_id` | yes | string | Logical ID, unique within the document |
| `candidate_id` | yes | string | Logical ID of the candidate this segment realizes |
| `source_id` | yes | string | Logical ID of the source the range is taken from |
| `source_range` | yes | object | See below |
| `continuation_group` | no | string or `null` | Marks segments that are slices of one continuous take |
| `verified_safe_end_frame_exclusive` | no | integer or `null` | Evidence-backed maximum safe out-point |
| `planned_record_frame_relative` | no | integer or `null` | Caller's intended relative placement, for verification |

`source_range` has exactly two keys:

| Key | Required | Type | Meaning |
| --- | --- | --- | --- |
| `start_frame` | yes | integer | Inclusive first frame in the source |
| `end_frame_exclusive` | yes | integer | Exclusive end frame; must be greater than `start_frame` |

## Canonical integer frame semantics

Frames are integers. This version accepts no other numeric form:

- Canonical integer frames only. Booleans and JSON numbers with a fractional
  part are rejected.
- **Second-based authoritative input is rejected by name.** A key such as
  `source_in_seconds`, `source_out_seconds`, `*_sec`, or `*_secs` is a contract
  error, not an ignored field. A rounded decimal must not silently become the
  basis of a boundary decision; callers convert seconds to exact frames before
  calling preflight.
- Non-negative frames only where the field describes a position or duration.

## End-exclusive source range semantics

`[start_frame, end_frame_exclusive)` — the start frame is included, the end
frame is the first frame *not* included. `duration_frames` is
`end_frame_exclusive - start_frame`.

## Verified safe boundary semantics

`verified_safe_end_frame_exclusive` is an evidence-backed maximum safe
out-point for that segment's source. The guard compares the proposed
`end_frame_exclusive` against it and reports
`SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY` when the proposal goes past it. A safe
boundary equal to the proposed end passes; a safe boundary beyond the proposed
end also passes, because the segment may simply not consume its whole verified
window.

## Continuation and candidate boundary semantics

The guard examines each adjacent pair of segments. It reports
`CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE` only when **all three** hold:

1. the two segments share the same `source_id`,
2. their ranges are contiguous (`left.end_frame_exclusive` equals
   `right.start_frame`), and
3. both carry the same non-empty `continuation_group`.

A boundary failing any one condition is accepted. In particular, a
`continuation_group` on segments drawn from different sources does not trigger a
finding.

## Relative placement semantics

Placements are laid contiguously starting at relative frame `0`. A segment's
relative position is the sum of the durations of all preceding segments.

When `planned_record_frame_relative` is present, the guard compares it with the
computed contiguous position and reports
`TIMELINE_RELATIVE_PLACEMENT_MISMATCH` if they differ. When absent, the computed
position is used without complaint.

## Deterministic output

The report is JSON with sorted keys, a two-space indent, and a trailing
newline. Byte-identical input produces byte-identical output: no timestamps,
random identifiers, machine state, or environment data enter the report. Issue
ordering is stable and follows input timeline order — for each segment the
guard emits that segment's source-boundary issue, then that segment's
planned-placement issue, then the outgoing candidate-cut issue toward the next
segment.

## Guard report structure

| Key | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Echoes the contract version |
| `passed` | boolean | `true` when `issues` is empty |
| `segments_checked` | integer | Number of segments accepted into the guard |
| `total_frames` | integer | Sum of all placement durations |
| `issues` | array | Business boundary findings, in timeline order |
| `placements` | array | Resolved contiguous placement geometry |

Each `issues` entry:

| Key | Type | Meaning |
| --- | --- | --- |
| `code` | string | Stable machine-readable issue code |
| `segment_ids` | array of string | One ID, or the adjacent pair for a cut issue |
| `source_id` | string | Source the finding is anchored to |
| `frame` | integer | Anchor frame of the finding |
| `reason` | string | Human-auditable explanation |

Each `placements` entry:

| Key | Type | Meaning |
| --- | --- | --- |
| `segment_id` | string | Segment the placement belongs to |
| `source_in_frame` | integer | Inclusive start frame |
| `source_out_frame_exclusive` | integer | Exclusive end frame |
| `duration_frames` | integer | Placement duration |
| `record_frame_relative` | integer | Resolved contiguous relative position |

Note that report placement keys are not named identically to the input range
keys: input uses `start_frame` / `end_frame_exclusive`, output uses
`source_in_frame` / `source_out_frame_exclusive`.

### Issue codes

| Code | Raised when |
| --- | --- |
| `SOURCE_OUT_EXCEEDS_VERIFIED_BOUNDARY` | Proposed source out-point passes the verified safe boundary |
| `CANDIDATE_BOUNDARY_SPLITS_CONTINUOUS_SOURCE` | Adjacent segments cut through one continuous source |
| `TIMELINE_RELATIVE_PLACEMENT_MISMATCH` | Planned relative placement disagrees with contiguous geometry |

## Contract error versus business boundary issue

These are different failure modes and must not be confused:

| | Contract error | Business boundary issue |
| --- | --- | --- |
| Meaning | The document does not satisfy this contract | The document is well-formed but describes an unsafe edit |
| Where reported | stderr, as an error message | stdout, as a report entry with `passed: false` |
| Exit code | `1` | `2` |
| Typical cause | Unknown key, wrong version, non-integer frame, duplicate ID, path-like ID | Out-point past a safe boundary, split continuation, placement mismatch |

A malformed document never produces a guard finding, and a guard finding never
masquerades as a program failure.

## CLI

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m src.ai_autocut.preflight INPUT.json
```

Run from the repository root.

| Exit code | Meaning |
| --- | --- |
| `0` | Input valid, boundary preflight passed |
| `1` | Input format, schema, contract, or runtime error |
| `2` | Input valid, but the guard found boundary business issues |

## Identifier rule

`segment_id`, `candidate_id`, `source_id`, and `continuation_group` are logical
identifiers, not filesystem locations. A value that looks like a local path — a
leading `/`, `~`, or `\`, a Windows drive prefix such as `C:\`, or any
backslash — is a contract error, and the offending value is deliberately not
echoed back, because it is a path. This keeps machine-local absolute paths out
of the audit report by construction rather than by filtering.

## Minimal valid example

The smallest document that passes: one segment carrying only the required keys.

```json
{
  "schema_version": "boundary_preflight.v1",
  "segments": [
    {
      "segment_id": "SEG-01",
      "candidate_id": "CAND-A1",
      "source_id": "SRC-A",
      "source_range": { "start_frame": 100, "end_frame_exclusive": 130 }
    }
  ]
}
```

This passes with exit code `0` and reports `passed: true`, `segments_checked: 1`,
`total_frames: 30`. It consumes none of the optional fields.

A fuller two-segment example that exercises `verified_safe_end_frame_exclusive`
and `planned_record_frame_relative` lives at
`tests/fixtures/boundary_preflight_v1_valid.json` and is executed by the test
suite.

## Compatibility rule

Version 1 is closed. This contract validates with a strict key allowlist, so an
unrecognized key is a contract error by design — there is no room for additive
optional fields inside v1.

Any of the following requires a new schema version (`boundary_preflight.v2`) and
a new contract document, not an edit to this one:

- adding, removing, or renaming a top-level or segment field
- changing the type or meaning of any field
- adding a new business issue code, or changing an existing code's meaning
- changing an exit code's meaning, or the deterministic output ordering

A `boundary_preflight.v1` document must keep validating exactly as described
here.
