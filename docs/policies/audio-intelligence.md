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
| Voice / music **synthesis** | **NOT_IMPLEMENTED** |
| Program verification (FIT / SYNC / RHYTHM) | **IMPLEMENTED** — `src/ai_autocut/audio_program.py` |
| Job-scoped **mixing and mastering** | **IMPLEMENTED** — `src/ai_autocut/execution_adapters.py` |

The three parts are deliberately listed separately, because they have genuinely
different status.

**Synthesis does not exist in this repository.** No module calls a voice, music or
sound-effect provider. Provider identity is recorded in
`docs/providers/audio-provider.md`; the provider was selected by validated work and
is not re-selected here.

**Program verification is implemented and wired.** `audio_program.assess_program`
judges FIT, SYNC and RHYTHM separately and runs in the `BUILD THE AUDIO` stage,
after placement and before the mix is accepted. FIT alone is never approval, and
there is no universal sync tolerance: a job that supplies none gets
`REVIEW_REQUIRED` rather than a borrowed number.

**Mixing and mastering are implemented at job scope.** `execute_audio` mixes a
job's own local assets with FFmpeg, applies the loudness and true-peak targets the
job states, and then *measures* the result — integrated loudness, true peak and
sample peak — refusing a mix whose sample peak reaches full scale. It makes no
provider call. This is not a universal audio engine: the assets, targets and
ceilings all come from the job.

Consequently the execution proof demonstrates the mixing and mastering path, not a
real voice performance. That distinction is recorded in `README.md`.

## Environment / Evidence Audio — production rules after V2

These rules guide source selection and review; the current local mixer does not
classify speech or establish sound provenance automatically.

| Class | Production treatment |
|---|---|
| Generated VO | Main narrative; one consistent speaker, clear and intelligible |
| Original Dialogue | Includes Chinese ads, source narration and any person speaking; exclude from ambience beneath Generated VO |
| Environment / Ambience | Verified clean location sound / room tone; quiet spatial context |
| Evidence Sound | Real action-linked sound, such as water flow or rinsing; preserve only against matching visible action |
| Handling / Foley-like Source Sound | Real installation, tightening, handling or object contact from source; retain provenance and synchronize |
| BGM | Separate licensed/existing music layer; below VO, never a substitute for real environment |
| SFX | Separate intentional effect; never label generated or library sound as real source evidence |

Generated VO and Original Dialogue must not collide. An original advertising
track does not become ambience just because its gain is reduced. Speech detection
or ASR returning no words is insufficient proof that a window is clean: inspect
and listen to candidate source windows, including their edges. Uncertain windows
are rejected, not mixed by default.

For each retained window record source identity, source in/out, destination
in/out, class, observed matching action, no-dialogue review, gain and short
fade/crossfade. Use the existing Audio Program and producer/input seam to supply
trimmed/faded assets and levels. Keep environment clearly below VO, enter/leave
with the action, and audition the combined result. This documentation does not
claim the current mixer automatically supplies ducking or dialogue separation.

Prioritize trustworthy real water, rinse, installation, handling, kitchen and
contact sounds when the picture supports them. If source sound is inadequate,
**clean VO is an acceptable output**. Do not mechanically repeat a 0.5–1 second
water fragment, restore original Chinese dialogue, attach mismatched action
sounds or call an unverified track “room tone”. Do not fabricate filtration or
other product-result evidence through sound.

The accepted V2 had only about **1.07 seconds** of trustworthy clean source sound
in about **43.87 seconds**. This is a recorded limitation of that job, not a target
coverage ratio and not proof of a reusable environment-audio system.

### Capability gaps (record only; no implementation in this change)

| Capability | Status and boundary |
|---|---|
| Automatic reliable classification of dialogue vs clean environment | **NOT_IMPLEMENTED**; producer review remains required |
| Reliable Original Dialogue separation with artifact checks | **NOT_IMPLEMENTED / NOT_WIRED** in the formal local path |
| Automatic action-aware environment selection and timing | **NOT_IMPLEMENTED**; source/destination windows are producer inputs |
| Environment / Foley fallback | **NOT_IMPLEMENTED / NOT_WIRED**; no synthesis or retrieval engine added |

Future fallback could cover room tone, water/rinse, installation/handling and
object contact. It must have trustworthy provenance/licensing, match the visible
action and space, remain below VO, and be identified as fallback rather than real
source evidence. It must not imply an unproven product result. These are future
acceptance principles, not authorization to build or use that system now.

For continuous Seed Audio performance direction use
[Audio Provider — Reusable Voice Direction](../providers/audio-provider.md#reusable-voice-direction--production-guidance).

### Cushion Puff production closeout — VO first

Human listening of the actual performance takes precedence over technical audio
checks for naturalness, pauses and incidental noise. A decoder, waveform, ASR or
loudness PASS is not listening approval. Do not add environmental noise by default
to manufacture “真人感”; judge optional environment separately from core VO.
Do not default to time stretching, post speed-up or internal-pause cutting. Align
picture to the approved native performance; re-align captions when audio changes.
See the [Human-validated voice profile](../providers/indonesia-beauty-creator-voice-v1.md)
for the accepted production example and its explicitly unproven prompt hypotheses.
