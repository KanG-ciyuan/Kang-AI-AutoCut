# Shot Intelligence Policy

## Staging

Analysis runs in three stages, cheapest first:

```
Rough Scan
  -> editing-relevant Candidate Analysis
  -> Fine Analysis on the narrowed set
```

Fine analysis is spent only on shots that survived the rough scan. Analysing
every frame of every source at full depth is the default failure mode of this
stage.

## What a Candidate Shot stores

Only facts that can change an **editing decision** — selection, ordering, or cut
timing.

A Candidate Shot must not become a general-purpose description of the footage.

## Deliberately out of scope

Not built by default, and not added "because it is available":

- dense optical flow
- 3D pose estimation
- all-object tracking
- hundreds of object classes
- per-frame captions
- a large vector database
- a graph database

A perception experiment tested whether Gold results required richer perception.
The finding was that the failures did **not** come from missing fields: the
information needed was already expressible in the existing content, visual
state, visual quality, and source-context fields, and the real problem was that
it had not been extracted finely enough. The conclusion was to stop expanding
the schema and start implementing.

## Material Gap

Material Gap is measured as **narrative beat visual evidence coverage** — which
narrative beats the available shots can actually prove with pictures.

It is **not** a clip count. Ten clips that all show the same beat leave the same
gap as one.

## Candidate Boundary is not a Timeline Boundary

A Candidate Boundary is evidence that a cut is *possible* there. It is not
approval of a cut. The historical reviewer explicitly flagged the failure of
treating the first as the second.

Placement, timing, and relationship between shots remain Editing Intelligence
decisions.

## Match-on-action

Match-on-action does not depend on source identity. Two shots from different
sources can carry a continuous action, and two shots from the same source can
fail to. Source identity is not the test; the action state at the boundary is.

## Status

| Part | Status |
|---|---|
| Policy | Documented here |
| `candidate_shot.v0` contract | **DRAFT** — `schemas/candidate_shot/` |
| Automatic extraction from raw media | **NOT_IMPLEMENTED** |

No module in this repository currently analyses media to produce a Candidate
Shot. The policy and a draft contract are recorded; the extractor does not
exist.
