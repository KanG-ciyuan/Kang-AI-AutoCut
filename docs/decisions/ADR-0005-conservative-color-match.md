# ADR-0005 — Conservative color match, product authenticity first

- **Status:** Accepted
- **Date:** 2026-09-14

## Context

Footage from different sources cuts together with visible discontinuity:
luminance jumps at cuts, mismatched white balance, and an overall "downloaded
video" feel. The obvious fix — matching every shot to a common statistical
target — was tested and rejected.

Aggressive matching measurably damaged the product. One candidate converged
background discontinuity well but overcorrected at a specific cut and darkened a
segment substantially; another left a coverage gap where the product region was
not protected at all.

The measured trade-off was explicit: the conservative variant converged less
(39% against 42%) and in exchange produced **exactly zero** change in the
product's blue channel across three shots.

## Decision

Color match exists to **reduce destructive discontinuity while protecting
product identity** — not to make sources statistically identical.

**Product color protection outranks statistical match.**

Priority:

1. background luminance jumps
2. destructive white-balance differences
3. obvious visual discontinuity

And explicitly avoided: overcorrection, product color drift, forced uniformity.

## Consequences

- Match, not grade. Adjustments move *toward a neighbour*; no look is imposed.
- The toolbox contains no LUT, film emulation, teal-orange, vignette, glow, or
  bloom. Transitions remain zero: every cut is a hard cut, and color is never
  used to hide a cut.
- A shot may legitimately be `KEEP`. Per-shot judgement is expected, and
  uniformity is not a goal.
- Unchanged cuts are a valid outcome. "The worst cut in the film became an
  ordinary cut" is success.

## Parameter scope

The specific correction numbers belong to **that footage**. They are recorded as
a Gold measurement, not promoted into a universal preset. A future job starts
from the principle and re-measures; it does not apply these numbers.

## What this forbids

- Matching all shots to one statistical target.
- Applying a global LUT.
- Letting a background improvement change product color.
- Copying the Gold correction numbers into a default configuration.
