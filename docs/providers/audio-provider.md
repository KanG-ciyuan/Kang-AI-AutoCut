# Audio Provider Boundary

## Position

The audio provider was selected by validated production work. It is **not
re-selected here**, and this repository does not re-open that decision.

## Current production provider

**Doubao / Seed Audio** is the current production audio provider, validated model
**`seed-audio-1.0`**. It is used for:

- Indonesian voice-over
- BGM
- generated SFX / ambience

The provider client lives **outside this repository**, so this repository performs
local mixing and mastering on job-local assets and ships no synthesis client. The
production fact and the repository fact are both true and are deliberately not
merged into one sentence.

**Not current production providers:** MiniMax (a past evaluation, below) and macOS
`say`. Neither is used for production audio today.

## Earlier validation — MiniMax

Voice-over was produced through **MiniMax `speech-2.8-hd`** (`POST /v1/t2a_v2`).

The exposed control surface was verified from the real API rather than assumed,
and the report explicitly refused to invent parameters that do not exist:

```
voice_setting:  voice_id, speed, vol, pitch, emotion
audio_setting:  sample_rate, bitrate, format, channel
                language_boost, subtitle_enable, subtitle_type, output_format
```

There is **no natural-language style prompt**. Direction is achieved through the
real parameters above, not through prose.

Two consequences were carried into the Audio policy:

- `speed` compresses phonemes but **does not compress comma pauses**, so the
  speed curve flattens. Past a point, more speed buys almost nothing, which is
  why "generate it faster" is not a general fix for a line that does not fit.
- No sound-effects endpoint was available, so sound-effect work could not be
  delegated to this provider.

## Why this changes the voice-over strategy

Because the same prompt does not reliably reproduce the same sampled speaker,
per-sentence generation risks an inconsistent narrator. The provider boundary is
one of the reasons `CONTINUOUS_PERFORMANCE_CUT_INTO_SEGMENTS` is the default —
see `docs/decisions/ADR-0006-continuous-voice-over.md`.

## Credentials

No key, token, endpoint secret, or provider dump is stored in this repository.

A provider integration refers to credentials by **environment variable name**
only, and configuration examples carry **placeholders**, never values. Provider
raw outputs (source generations, stems, intermediate WAVs) are large generated
media and stay outside Git under `AUTOCUT_MEDIA_ROOT`.

## Integration shape

```
planning  ->  provider call  ->  raw output (external)
                              ->  mix / master (external)
                              ->  identity + hash recorded in Gold manifest
```

The repository records **that** a provider produced an asset and **which hash**
identifies it. It does not store the asset.

## What this forbids

- Re-selecting the audio provider.
- Assuming a parameter exists because a style prompt would be convenient.
- Using provider hard truncation to force a line into a duration.
- Committing keys, tokens, provider dumps, or generated audio.

## Reusable Voice Direction — production guidance

For the Human-validated Indonesia Beauty profile, use the current
[Voice v1 production practice](indonesia-beauty-creator-voice-v1.md). It supersedes
the older generic performance scaffold below for this profile: direct semantic
actions/attitudes, not filler pitch or planned micro-pauses.

Use this guidance in **BUILD THE AUDIO**, after Spoken Copy approval and before
calling the existing external Seed Audio client. This is a Production Agent task,
not a new provider, agent, or deterministic prompt builder. V2 production validated
the usefulness of natural-language direction; it did not prove that any prompt
will always produce a natural performance.

Read the current job's **target market/language, platform, commercial objective,
copy style, product category and locked Spoken Copy**. Derive direction from this
brief and the actual copy. Do not regenerate Commercial Strategy or rewrite the
copy. If a required fact is absent, use a neutral performance direction rather
than inventing buyer demographics, personal experience, or product claims.

Compose one concise natural-language prompt with these decisions:

1. **Persona and relationship.** Choose one speaker throughout. State perceived
   age/gender only when the job provides or authorizes them. Describe a close,
   credible relationship (seller explaining, friend recommending, user-style
   presentation). These are acting directions, not assertions of real identity
   or personal product use. Do not add “I tried this” to the approved copy.
2. **Market and tone.** Use the approved target language and the job's local
   conversational register. For an Indonesia TikTok Commerce friend-recommendation
   brief, natural, friendly, close conversation is appropriate. This is an example,
   not a default female Indonesian persona for every market or SKU.
3. **Emotional arc.** Map only beats that actually exist in the copy: a curious,
   mildly concerned or relatable Hook; a willing, lightly smiling recommendation;
   plain, credible explanation; selective emphasis on an existing benefit; a
   relaxed CTA invitation. Do not apply all emotions to every line or strengthen
   claims through exaggerated certainty.
4. **Rhythm.** Ask for conversational variations in pace, unequal short pauses,
   small natural breaths, and selective stress. Preserve a continuous performance,
   including transitions. A duration target is guidance, not permission to omit
   words, hard-truncate speech or accelerate beyond intelligibility.
5. **Negative directions.** No announcer or TV-commercial delivery, live-selling
   shouting, flat mechanical TTS, equal force on every sentence, word-by-word
   reading, theatrical acting or long artificial pauses. No extra words, fillers,
   effects, translation, claims or spoken stage directions.

Produce a prompt ready for the existing client's **natural-language text_prompt**:

```text
Perform one continuous voice-over in [approved language] for [market/platform].
Use one consistent [job-authorized persona] speaking naturally to one person,
with [relationship and tone from the brief].
[Brief emotional arc mapped to the actual approved copy.]
Use conversational pacing, varied short pauses, subtle breaths and selective
emphasis. Keep the explanation credible and the invitation relaxed.
Avoid announcer delivery, shouting, mechanical equal emphasis, long artificial
pauses and overacting. Read only the exact approved words below; do not speak
these instructions, add words, omit words or change their meaning.
BEGIN APPROVED SPOKEN COPY
[insert locked Spoken Copy verbatim]
END APPROVED SPOKEN COPY
```

Replace bracketed direction with concrete job choices; omit irrelevant beats.
Keep the approved text and the direction separate in the job record. Use the
existing verified client request shape; natural-language speed/prosody direction
is **not** evidence of supported numeric `speed`, `emotion` or `voice_id` API
fields. Do not borrow historical MiniMax controls. Credentials stay external.

After synthesis, review a **single continuous take**, retain the raw asset, and
check words, language, speaker consistency, rhythm and intelligibility. Record
model, direction, actual exposed settings, source/final hashes and any approved
pause repair. Subjective naturalness still requires listening. If VO is changed
or silence is edited, align words to the **final** VO again before captioning;
never reuse raw-generation timestamps against edited audio.

### Human-validated production practice — Cushion Puff closeout

The accepted example is **Global Persona + Local Semantic Performance**: 导演人物，不导演音素。
This is production-supported working practice, not proof of a model-internal
quotation/newline/continuation-word mechanism. One-sample A/B and later changed
copy/output direction do not establish causal superiority; record this boundary.

Reuse the exact Human-selected reference and official rate for that voice profile.
For an authorized production round, generate three identical-config continuous
takes by default and let Human / an actual listening Reviewer choose; bounded
experiments follow their specified call count. Technical audio checks never replace
or overrule Human listening on naturalness. A chosen take stops automatic rerolls.
Do not default to post speed-up, pause compression or splicing to repair performance.
Keep core VO clean by default; assess optional scene sound separately. Preserve raw
voice, actual request/prompt, selected take and final artifact hashes.
