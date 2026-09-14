# Audio Intelligence Policy

## Two orthogonal dimensions

The central rule: **event state is not mix role.**

| Dimension | Answers | Values |
|---|---|---|
| **Event State** | what is the picture doing? | `OFF`, `ONSET`, `FLOW`, `IMPACT`, `DECAY` |
| **Mix Role** | how present is this sound? | `BED`, `EVIDENCE`, `HERO` |

Collapsing these into one axis is what produces water noise under a dry shot. A
continuous ambience can be a `BED` *and* an event; a one-off impact can be
`HERO` and brief. They are independent, and the model keeps them independent.

## Visual evidence outranks preplanned audio timing

**Visual evidence > preplanned audio timing.** Sound follows what the picture
actually shows, not what the plan expected it to show.

The operative rule:

> **A dry visual shot has water `OFF`.**

If a shot contains no water evidence, no water sound belongs on it — regardless
of what the audio plan predicted, and regardless of the fact that neighbouring
shots do have water. Silence in a dry shot is correct, not a gap to fill.

The validator enforces this: `WaterEvent` refuses a non-`OFF` state for a shot
without water evidence, and refuses a non-`BED` mix role on an inactive event
state.

## Mix priority

```
VO > Evidence Water / Foley > BGM
```

Voice always wins. Background music yields.

## BGM structure

BGM is **structurally edited**, not laid end to end under the film:

```
Hook / Intro -> Product Build -> Usage Lift -> CTA Resolve
```

The validator requires exactly that structure. A single track played from 0:00
to the end is rejected, because a bed that never changes is doing no editorial
work.

## Sound bridges

A sound bridge across a cut is allowed **only with an explicit continuity
reason**. Carrying audio across a boundary asserts that the two shots are
continuous; without a reason, that assertion is false and the bridge is
decoration. `SoundBridge` refuses an empty reason.

## Voice

One continuous performance, cut into segments — see
`docs/decisions/ADR-0006-continuous-voice-over.md`. This is the default because
per-sentence generation does not reliably reproduce the same speaker.

Suggested timing windows are targets, not laws. Natural performance outranks
forced mechanical timing, and provider hard truncation is not an accepted way to
hit a duration.

## Loudness

The validated Gold result measured:

| | Value |
|---|---|
| Reference target | ≈ −16 LUFS, ≈ −1.4 dBTP |
| Measured on the final MP4 | ≈ −16.1 LUFS, −1.4 dBTP |

**This is a Gold reference, not a universal platform law.**
`audio_plan.GOLD_REFERENCE_IS_UNIVERSAL` is `False`, so a future job re-measures
for its own delivery target rather than inheriting these numbers as a rule.

True peak is checked **after** AAC encoding, on the delivered MP4 — not only on
the pre-encode WAV, because encoding can raise the peak.

## Staging

```
Creative Audio PASS -> then Mastering
```

Creative judgement and loudness delivery are separate gates.
`assert_creative_pass_before_mastering` enforces the order.

## Status

| Part | Status |
|---|---|
| Policy | **VALIDATED** — `src/ai_autocut/audio_plan.py` |
| Schema | `schemas/audio_plan/audio_plan.v0.schema.json` |
| Synthesis, mixing, mastering | **NOT_IMPLEMENTED** |

Audio provider identity is recorded in `docs/providers/audio-provider.md`. The
provider was selected by validated work and is not re-selected here.
