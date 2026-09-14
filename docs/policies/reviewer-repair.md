# Reviewer and Repair Policy

## The governing rule

> **A Reviewer is not the Executor's self-declaration.**

A component reporting that it succeeded is a claim. Review is an independent
judgement of the result against the intent. The two must be different actors,
and `review.Review` refuses a review whose `reviewer_id` equals its
`executor_id`.

## Three gates

```
Deterministic QA  ->  Independent AI Review  ->  Human Final Gate
```

Each gate answers a different question:

| Gate | Question |
|---|---|
| Deterministic QA | are the measurable properties correct? |
| Independent AI Review | is the edit good, judged across dimensions? |
| Human Final Gate | is this acceptable to ship? |

Passing one gate says nothing about the others. A technically correct export is
not a good edit, and a good edit is not a release decision.

## Severity

| Severity | Meaning | Disposition |
|---|---|---|
| `PASS` | no issue | — |
| `WEAK` | real but acceptable | may be **explicitly accepted**, and the acceptance is recorded |
| `FAIL` | must be repaired before release | cannot be accepted |
| `CRITICAL` | returns to planning | cannot be accepted, not repaired by a targeted fix |

## Release verdict

Derived, not asserted:

| Condition | Verdict |
|---|---|
| any `CRITICAL` | `REJECT` |
| any non-accepted `FAIL` or `WEAK` | `NEEDS_REPAIR` |
| otherwise | `PRODUCTION_READY` |

A verdict is a function of recorded findings, so it cannot be improved by
rewriting a summary. The only way to change the verdict is to change the
evidence.

## Dimensions

Review covers exactly the ten Editing Intelligence dimensions listed in
`docs/policies/editing-intelligence.md`. Each is judged once; a duplicate or
unknown dimension is a contract error, so a review cannot quietly omit an
inconvenient dimension by re-labelling it.

## Repair

Repair is **targeted**: the smallest affected range. See
`docs/decisions/ADR-0008-targeted-repair.md`.

A repair must be verifiable against its baseline. The validated audio repair set
its adjustment to zero and confirmed the output was byte-identical to the
previous mix — that is what "targeted" means in practice: proof that nothing
else moved.

A `REJECT` verdict is **not** repaired by a targeted fix. It returns to planning.

## Self-review, and the human gate

`Review.requires_human_gate` returns `True`. Release always passes the human
gate, and repair never auto-releases. This is not a limitation to be optimized
away later; creative acceptance is a human judgement.

## Status

| Part | Status |
|---|---|
| Contract | **VALIDATED** — `src/ai_autocut/review.py` |
| Schema | `schemas/review/review.v0.schema.json` |
| Automated reviewer agents | **NOT_IMPLEMENTED** |

The contract defines how a judgement is recorded and what it implies. It does
not produce judgements.
