# ADR-0008 — Targeted repair by default, never full regeneration

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

When review finds a defect, the cheapest action to *describe* is "regenerate the
video". It is also the most destructive: it discards validated work, re-rolls
creative decisions that already passed, and makes the result non-comparable to
the artifact that was reviewed.

The validated work repaired problems by narrowing scope instead. A color defect
was fixed at named shots; an audio defect was fixed with a gain change on one
line over its own window.

## Decision

Repair follows a review and is **targeted to the smallest affected range**.

Regenerating an entire video or voice track is **not the default** and is
refused unless a specific decision authorizes it.

## Consequences

- `review.build_targeted_repair` refuses to produce a plan with no declared
  affected shots, and `RepairPlan` rejects `regenerate_entire_video=True`.
- `audio_plan.assert_targeted_repair` refuses an unscoped repair and refuses
  regeneration.
- A repair must be **verifiable against its baseline**. The validated audio
  repair proved its own containment by setting the adjustment to zero and
  confirming the output was byte-identical to the prior mix. A repair that
  cannot demonstrate it changed nothing else is not yet a targeted repair.

## Severity and release

| Severity | Meaning |
|---|---|
| `PASS` | no issue |
| `WEAK` | real but acceptable; may be explicitly accepted |
| `FAIL` | must be repaired before release |
| `CRITICAL` | returns to planning; not repaired by a targeted fix |

`FAIL` and `CRITICAL` can never be dispositioned away. Only `WEAK` may be
accepted, and acceptance is recorded.

Derived verdict: any `CRITICAL` → `REJECT`; any non-accepted `FAIL` or `WEAK` →
`NEEDS_REPAIR`; otherwise `PRODUCTION_READY`.

## What this forbids

- Regenerating to fix a local defect.
- An unverifiable repair, or one that changes global behaviour.
- Accepting a `FAIL` or `CRITICAL` finding.
- Repairing a `REJECT`: it returns to planning.
