# Backend-Neutral Executable Timeline

## Decision

Editing decisions are expressed **once**, in a backend-neutral Executable
Timeline. Backends are compilers that consume it. No backend owns the timeline
shape, and no backend's private project format is the source of truth.

```
Editing Plan
  -> Executable Timeline      (backend-neutral, frame-canonical)
  -> Backend Compiler
       -> FFmpeg              local deterministic render
       -> DaVinci Resolve     automated visual execution
       -> Jianying            editable delivery / human takeover
```

## Why this exists

The historical work validated three very different execution routes. Binding
editing decisions to any one of them would have made the other two lossy
conversions:

- DaVinci Resolve speaks in its own project and timeline objects.
- Jianying speaks in a draft file that it rewrites on open.
- FFmpeg speaks in a filter graph.

A single contract keeps the decision layer free of all three dialects, and makes
"what was decided" separable from "how it was rendered".

## Status

| Part | Status |
|---|---|
| Contract and invariants | **VALIDATED** — `src/ai_autocut/executable_timeline.py` |
| JSON Schema | `schemas/executable_timeline/executable_timeline.v0.schema.json` |
| FFmpeg compiler | **NOT_IMPLEMENTED** |
| DaVinci compiler | **NOT_IMPLEMENTED** |
| Jianying compiler | **NOT_IMPLEMENTED** |

`compile_for_backend` raises `NotImplementedError` for every backend. This is
intentional: a contract that returns a plausible-looking compiled timeline would
be worse than one that refuses.

## Frame-canonical rule

The contract is frame-canonical. Seconds-based fields such as
`source_in_seconds` are **contract errors, not values to be rounded**. A decimal
timestamp that is not exactly frame-aligned has no single correct meaning, and
guessing one silently changes a cut.

The frame rate is an exact rational (`"30/1"`), so 30 and 29.97 remain distinct
rather than collapsing into a float.

## Invariants

Enforced in the constructor and covered by tests:

1. Source ranges are end-exclusive and non-empty.
2. Record placement is strictly contiguous: **no gap and no overlap**.
3. `segment_id` is unique within a timeline.
4. Frames are integers and non-negative.
5. `source_id` is a logical identity, never a filesystem path.
6. Dimensions and frame rate are positive.

Gaps and overlaps are rejected rather than flagged, because a gap is not a
warning in an execution plan: it is an undefined region of the output.

## Relationship to the frozen contracts

`executable_timeline.v0` sits **downstream** of the already-frozen
`candidate_pool.v1`, `editing_plan.v1`, and `material_candidate_identity.v1`
chain. It does not replace them and does not redefine Candidate or Material
identity. The existing `boundary_preflight.v1` binding continues to run before
any timeline is compiled.

## Compatibility rule

Version 0 is a draft. Field changes require a separately reviewed version.
Adding a backend does not change this contract; it adds a compiler.
