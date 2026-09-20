# Editing Intelligence Policy

## Where it sits

Editing Intelligence runs **after** Creative Intent and the Shot Pool are known,
and **before** any timeline is compiled.

```
Creative Intent + Shot Pool
  -> Editing Intelligence
  -> Editing Plan
  -> Executable Timeline
  -> Backend Compiler
```

## What it decides

- shot selection
- time range
- placement and cut timing
- shot relationship
- rhythm
- information density
- continuity, and intentional discontinuity
- commercial effectiveness

## What it is not

Not material analysis, not the creative director, not the renderer, and not a
simple clip list. It receives analysis and intent; it produces an edit.

Material analysis answers *what is in the footage*. Editing Intelligence answers
*what should be shown, in what order, for how long, and why*.

## Separation of duties

| Stage | Owns |
|---|---|
| Shot Intelligence | what the footage contains |
| Creative Intent | what the piece should achieve |
| Editing Intelligence | the edit decision |
| Renderer | executing the decision |
| Reviewer | judging the result independently |

A component may not occupy two of these roles. In particular, the component that
produces an edit does not judge it — see `docs/policies/reviewer-repair.md`.

## Reviewer dimensions

An edit is judged on exactly these ten dimensions, each answered once:

1. Shot Selection
2. Action Boundary
3. Shot Relationship
4. Narrative Progression
5. Rhythm
6. Multi-source Remix
7. Information Density
8. Visual Continuity
9. Effect Judgment
10. Commercial Effectiveness

`review.REVIEWER_DIMENSIONS` is the machine-readable copy of this list, and the
parser rejects a review that judges an unknown dimension or judges one twice.

## Frozen representation

The *decision* is frozen in `editing_plan.v1`: an ordered, content-addressed
selection of complete Candidates from one Candidate Pool. It stores no source
facts, no trim ranges, no timeline state, and no explanations — those belong
upstream or downstream, not in the decision.

## Status

| Part | Status |
|---|---|
| Policy and reviewer dimensions | Documented here |
| `editing_plan.v1` | **FROZEN** with implementation and tests |
| vNext companion contracts (`candidate_evidence.v1`, `hook_decision.v1`, `planning_evidence.v1`) | **CONTRACT_ONLY** — validated shapes, no production writer or reader |
| Automated Editing Intelligence from a Shot Pool | **NOT_IMPLEMENTED** |

`CONTRACT_ONLY` means the contract exists and is tested, and nothing in the
production path uses it. The three companion documents are described in
`docs/contracts/`. Nothing in this repository generates Candidate Evidence,
generates or selects a Hook, or plans a sequence yet.

The frozen contract preserves decisions that were made. Nothing in this
repository yet makes them automatically from raw material.
