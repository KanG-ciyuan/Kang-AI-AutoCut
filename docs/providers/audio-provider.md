# Audio Provider Boundary

## Position

The audio provider was selected by validated production work. It is **not
re-selected here**, and this repository does not re-open that decision.

## What was validated

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
