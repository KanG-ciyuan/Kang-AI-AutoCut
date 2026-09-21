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
| Candidate Evidence (`candidate_evidence.v1`) | **SUPERSEDED IN SHADOW** — produced from measured material in `VNEXT_SHADOW`, still parsed/migrated; no production reader |
| Candidate Evidence (`candidate_evidence.v2`) | **IMPLEMENTED IN SHADOW** — adds structured visual observations; produced under `candidate_evidence_prompt.v3` |
| `hook_decision.v1` | **PRODUCED IN SHADOW** — written by `DECIDE THE HOOK`; validated shape, one creative call, deterministic veto |
| `planning_evidence.v1` | **CONTRACT_ONLY** — validated shape, no writer and no reader anywhere |
| Live multimodal analyzer over real Candidate frames | **HARNESS AVAILABLE, RUN NOT PRESERVED** — the opt-in harness can sample frames with exact source-frame labels, hand them to an analyzer, and audit the answer; a run performed during development reported a model reading those frames, but its artifacts were not preserved in the repository and no independent party has verified that run |
| Hook Planning | **IMPLEMENTED IN SHADOW** — one versioned prompt (`hook_decision_prompt.v1`), one model call per run, consuming only authoritative structured fields and never `rationale` |
| Hook generation and selection | **IMPLEMENTED IN SHADOW** — the model ranks; a deterministic gate vetoes on declared facts, support honesty and required evidence, and never compares two viable angles. One eligible hypothesis is selected, several leave a *pending* decision, none means insufficient |
| Sequence planning and timeline compilation | **NOT_IMPLEMENTED** |
| Automated Editing Intelligence from a Shot Pool | **NOT_IMPLEMENTED** |

`CONTRACT_ONLY` means the contract exists and is tested, and nothing writes or reads
it anywhere. `IMPLEMENTED IN SHADOW` means it runs, is tested, and is deliberately
outside the production path: a shadow run produces and validates Candidate Evidence
and a Hook Decision, and nothing consumes either to choose a shot or a cut.
`HARNESS AVAILABLE, RUN NOT PRESERVED` separates a capability from a result: the code
can do it, and no replayable evidence of it doing so is kept here.

So, precisely: this repository **does** now produce Candidate Evidence and a Hook
Decision in shadow, with and without a live analyzer; it still has **no production
reader** of either, and **no sequence planning**. The contracts are described in
`docs/contracts/`.

Two limits of the Hook Decision stage are worth stating rather than discovering:
the fact gate performs **declared Product Fact reference validation** - it checks the
facts a hypothesis names, and cannot prove a premise declared every fact it rests on
without parsing commercial prose; and eligibility is read from structured evidence, so
the "old way is worse" half of an `OLD_WAY` premise is enforced only as the fact
allow-list plus the two required observations. The required observations themselves are
only as good as the analysis that recorded them.

The frozen contract preserves decisions that were made. Nothing in this
repository yet makes them automatically from raw material.
