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
| Art Direction baseline | **LOCKED** — `src/ai_autocut/typography_art_direction.py` |

`POLICY_VALIDATED_IMPLEMENTATION_PENDING` is the recorded status, and
`typography.assert_placement_implemented` raises rather than returning
positions. No module here analyses an image or renders text.

The policy is the part that survived real review; the solver is future work, and
the two are kept visibly separate.

---

# Typography Art Direction A v1 — LOCKED BASELINE

The Third SKU's typography was designed by hand three times — V1, an outside
"Work" revision, and finally a **Premium Minimal A** exploration. The human
Producer accepted A and locked it as the project's typography baseline.

V1 is the reason A exists. V1 was one flat white Arial Bold, one fixed baseline,
no stroke, no shadow, no plate, no keyword emphasis and no motion; it read as
ordinary. A answers that with a condensed heavy grotesque, a warm-white body and
a desaturated warm-gold emphasis, a light stroke and soft shadow instead of a
dark plate, and a restrained fade-and-settle.

`src/ai_autocut/typography_art_direction.py` turns that decision into something
the **next** SKU can reuse. It is a rule set plus a controlled zone system, not a
renderer: it decides *where text may sit and whether a layout is acceptable*, and
refuses everything else.

## Rules and parameters are different things

This is the distinction the module exists to keep, and the reason it can be
reused at all.

**Art Direction Rules** generalise across SKUs. They are the constants in the
module.

1. Premium minimal.
2. Consistency first, adaptation only when necessary.
3. Body selling points use a stable upper typography zone.
4. Body uses a stable visual anchor and does not drift shot to shot.
5. Only a real conflict — product, hand/action, result/evidence or platform safe
   zone — permits a limited fallback zone.
6. Hook, body and CTA are different narrative roles.
7. The three roles may carry different visual weight but share one design language.
8. Hierarchy comes from size, weight and a restrained accent colour.
9. Large dark information plates are avoided.
10. Legibility is bought with whitespace, type hierarchy and a light
    stroke/shadow.
11. Motion is restrained and serves reading only.
12. Typography never takes first visual priority from the product or the evidence.

**Adaptive Parameters** do not generalise, and must not become cross-SKU
defaults: font family and weight, the specific colours, the type scale, the line
breaks, the exact coordinates and the animation values. A's current values are
recorded as a **job-scoped profile** in
`examples/typography/art-direction-a-v1.profile.json`. A future job states its
own. A parameter promoted to a module default would be one SKU's art direction
silently applied to another — the same discipline this repository already applies
to geometry and to audio.

## The zone system

A layout names a **zone** from a closed set. Free positioning is not
representable: `TypographyEvent` refuses a zone name outside `ZONE_NAMES`, so an
"AI finds the best spot in the 1080x1920 frame" behaviour cannot be expressed,
let alone shipped.

```
HOOK                -> UPPER_LEFT
BODY_SELLING_POINT  -> UPPER_LEFT      (the stability anchor)
CTA                 -> UPPER_CENTER
```

Selection is deterministic and has no search: the role's default zone is used
whenever it is free, the role's fallback chain is walked in order only when a
real conflict exists, and if nothing fits, the layout is **refused** rather than
placed somewhere arbitrary. Evidence is supplied per event, because evidence
differs from shot to shot and one global set would make a conflict in a single
shot look like a conflict in all of them.

Body events inherit the anchor the body already established. A body event may
still take a fallback — but only because *that* event conflicts, and the
deviation is recorded so a reviewer can tell a justified deviation from drift.

## Review

`review_typography` reports fourteen named checks — text preserved, safe margin,
platform safe zone, clipping, product overlap, hand/action overlap,
result/evidence overlap, role hierarchy, body position consistency, CTA
visibility, background plate restraint, decorative excess, motion restraint and
mobile readability.

There is deliberately **no score**. "Premium" is not a measurable quantity, and a
0–100 number would launder a judgement call into a figure. Each check reports a
severity and its evidence; the human judges.

Text preservation is judged on the **word sequence**, not on line breaks. Line
breaking is an open visual parameter — A legitimately re-broke the approved lines
— while changing, adding, dropping or reordering a word is not.

## Status

Two claims are made about this baseline, and only one of them is settled.

```
ART_DIRECTION_RULES          = LOCKED
REFERENCE_PIXEL_REPRODUCTION = UNRESOLVED
```

| Part | Status |
|---|---|
| Art direction rules | **LOCKED** — `Typography Art Direction A v1` |
| Reference pixel reproduction | **UNRESOLVED** — not claimed |
| Rules + zone system + reviewer | **IMPLEMENTED** — `src/ai_autocut/typography_art_direction.py` |
| Third SKU A parameters | `examples/typography/art-direction-a-v1.profile.json` |
| Tests | `tests/test_typography_art_direction.py` |
| Renderer | **NOT_IMPLEMENTED** — this module places and reviews text; it does not draw it |

The Third SKU's approved artefacts — V1, V2 and the A exploration — are reference
and approved evidence. None of them is modified by this baseline, and the module
does not depend on any of them at runtime.

**This baseline does not claim it can reproduce the approved A frames
pixel-for-pixel.** A's ASS spec and its overlay renderer state different pixel
sizes for the same events (the renderer is uniformly about 1.12x the ASS), and
which of the two produced the accepted frames is unknown. The discrepancy is
recorded rather than guessed.

It does not weaken the rules, which never mention pixel sizes. It does mean a job
adopting this baseline inherits the **design language** and must state and verify
its own pixel values — it may not cite this profile as proof that its render
matches A. That distinction is carried in the profile's `status_semantics` block
and asserted by `StatusSemanticsTests`, so it cannot quietly collapse back into a
single "LOCKED".

