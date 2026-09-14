# Shot-aware Typography Policy

## Purpose

Typography provides **editorial emphasis**. It is not subtitle delivery.

| Carrier | Responsibility |
|---|---|
| Picture and action | prove how the product works |
| Editorial text | emphasize what must be remembered |
| Voice-over | supplement, and carry what pictures cannot |

Text must not restate what the picture already proves. Per-sentence voice-over
subtitles are not a text role, and burning them is not an accepted use of this
system.

## Priority

```
Product first -> Action second -> Text third -> Decoration last
```

Text never displaces the product, and decoration never displaces text. A
conflict is resolved by rank, not by taste, and `typography.resolve_conflict`
implements the ordering.

## Placement considerations

Every text event is placed against what is genuinely in the shot:

`Product`, `Face`, `Hand`, `Action`, `Water`, `Important Object`,
`Avoid Zones`, `Negative Space`, `Visual Density`, `Text Role`, `Safe Area`,
`Mobile Preview`

At minimum, an event must declare `product`, `action`, `safe_area`, and
`mobile_preview`. Product and action dominate the frame; safe area and phone-scale
legibility are checked because the primary viewing surface is a phone.

## Text roles

Three roles, one event each: `hook`, `feature`, `cta`.

A Beat keeps one primary text event. When there is no new information, the right
move is usually no text at all.

## Visual direction

**Clean Product Commercial**, with premium minimal motion.

Allowed motion: `fade`, `micro_motion`, `easing`, `stagger`.

Refused by default: `bounce`, `rotation`, `glow`, `particles`, `arrows`,
`trajectory_lines`, `stickers`.

Directional graphics are refused specifically because they claim to explain
motion. A line drawn over a shot asserts a path the product may not take; when a
real product action needs explanation, the correct fix is a better shot, not an
arrow.

Emphasis is limited to **at most one term per event**, so a whole line is never
dyed one colour.

## Status

| Part | Status |
|---|---|
| Policy | **VALIDATED** — `src/ai_autocut/typography.py` |
| Schema | `schemas/typography/typography_policy.v0.schema.json` |
| Automatic shot-aware placement | **NOT_IMPLEMENTED** |

`POLICY_VALIDATED_IMPLEMENTATION_PENDING` is the recorded status, and
`typography.assert_placement_implemented` raises rather than returning
positions. No module here analyses an image or renders text.

The policy is the part that survived real review; the solver is future work, and
the two are kept visibly separate.
