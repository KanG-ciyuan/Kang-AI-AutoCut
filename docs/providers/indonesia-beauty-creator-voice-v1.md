# Indonesia Beauty Creator Voice v1 — production-validated example

2026-09-27. **Human validated for this reference, tested copy and accepted Cushion Puff result.** This is a reusable voice profile and production practice, not a promise that every take will sound natural. The fixed persona applies to this Indonesia Beauty profile, not all SKUs or markets.

## Verified / Human Validated

- Fixed reference: original no-number-suffix console WAV, 19.88s, 40000Hz stereo PCM16, exact original bytes. Human chose it, then accepted three new Beauty Brush-copy takes as reasonably matching its identity. This is bounded cross-copy evidence, not a universal speaker-identity guarantee.
- Reference SHA-256: `a63f8fb9f136fcb5a7dc1a8e5a90569ea2aa3816f661caf7d2fe16171c3b41cb`.
- Resolve job `cushion-puff-id-coldstart-20260926`; reference file: `audio/voice-reference-transfer-v1/reference/Indonesia-Beauty-Creator-Voice-Reference-v1-Candidate.wav`. Exact machine-local source/frozen paths and provenance are stored in the job's `audio/voice-profiles/indonesia-beauty-creator-v1/profile.json` and `closeout/final-production-lock.json`.
- Actual binding: base64 of the **complete original WAV bytes** in `references[0].audio_data`; the scene binds its actor with **饰演者为@音频1**. No persistent Speaker ID was created. Neither a generated take nor a mixed video becomes a new reference automatically.
- Domestic Doubao / Seed Audio, model `seed-audio-1.0`, endpoint `POST https://openspeech.bytedance.com/api/v3/tts/create`.
- Exact production parameters: `audio_config.format=wav`, `sample_rate=40000`, **`speech_rate=0`**, `pitch_rate=0`, `loudness_rate=0`, `enable_subtitle=false`; `watermark={}`. Credentials and raw encoded audio stay outside Git.
- Human chose Rate A = 0 over the two trial settings 8 and 15. Each setting had one sample; total durations also include performance variance and are not a linear speech-rate calibration.
- Final Cushion Puff uses dry VO v4 Take 1 (23.78s), SHA-256 `25d915c874e225fc9d7a4a51a3fdd1ad5ff80b514deed96d3683fa6860912434`. Human chose it over Takes 2/3 with excessive laughter; then passed the 24s final video. One previously reported knock-like sound remains and is accepted in this specific result, not declared absent.

## Production-supported working practice

**Global Persona + Local Semantic Performance. 导演人物，不导演音素。**

Use one stable character and audience relationship, then brief scene/action/intention/attitude tied to the copy's actual semantic beats. Send the whole approved script as one continuous generation. Do not prescribe each filler's pitch, pause duration, breath or required laugh. A smiling voice is not a requirement to insert audible laughter.

For an authorized production round, default to **3 takes with identical reference, model, prompt, copy, rate and other generation parameters**. Accept natural provider variation; Human or an actual listening Reviewer chooses the complete performance. Technical decode, waveform, ASR, duration and loudness checks cannot overrule Human listening on naturalness. Experiments retain their explicitly smaller call budget. Do not keep rerolling after a take is selected.

Request clean core VO by default. Environment sound, if needed, is a separate creative decision with its own provenance and listening review; do not automatically request desktop knocks or ambience to simulate authenticity. A dry-output instruction does not guarantee the generator produces no incidental sounds.

Do not default to post speed-up, time stretching, pause compression or sentence splicing to repair generated performance. Use the Human-selected native pace and align picture/captions to it. Here the 32.9s picture was tightened to 24s around a 23.78s voice, with a 0.22s tail; voice speed stayed unchanged.

## Not yet proven — no model-internal claims

The controlled prompt comparison used one sample per prompt: blind A = segmented V2, blind B = global V1; Human slightly preferred B. The conditional ablation was not run. Later production changed approved copy and dry-output direction before the selected Take 1 and final Human PASS. Therefore final success supports a usable production practice, **not** a proven causal advantage of segmentation or V2.

No determination that independent quotation blocks control prosody in a particular way, newlines necessarily cause long pauses, “继续介绍 / 补充道” have a fixed parser rule, or Console/API have hidden processing differences. Original Console request details were not captured. These remain hypotheses, not reasons to reopen research after a satisfactory result.

## Exact accepted production prompt

This is the historical **actual prompt**, not a cleaned-up reconstruction. In particular “满满的笑意 / 兴致勃勃” remained; the final outcome passed through take selection. Future SKU scene actions and attitude may be adapted when authorized, while reference identity and selected rate remain fixed. Do not copy puff-specific actions into an unrelated product.

```text
美妆博主 是年轻成年印尼女性，讲自然地道的日常印尼语，嗓音明亮、圆润有厚度，性格爽朗亲切，印尼美妆短视频带货风格，饰演者为@音频1

只输出单人的纯净干声，不要背景音乐、环境音、桌面物品磕碰声或其他声效。参考音频仅用于声音身份，不复现其中的背景声音。以下动作描述只提供展示场景，不生成动作声。只朗读引号内的印尼语，不朗读场景说明。
美妆博主带着满满的笑意，语速轻快，举着手里的气垫粉扑对着镜头边展示边兴致勃勃地开口，语气笃定又有感染力："Sudah dandan, tapi makeup di sisi hidung malah cakey. Kesel banget kalau begini."
美妆博主指尖轻轻捏起粉扑边缘对着镜头凑近展示，语气满是认可地继续介绍："Coba pakai puff ini. Teksturnya lembut, jadi makeup di sisi hidung bisa nempel lebih rapi dan nggak gampang cakey. Aku juga suka karena puff ini nggak nyerap foundation."
美妆博主把用过的粉扑举到镜头前晃了晃，语气轻快又贴心地补充道："Habis dipakai bisa dicuci, terus dipakai lagi buat makeup berikutnya. Lagi mau ganti puff? Ambil yang ini aja."
```

## Exact approved Indonesian spoken copy

```text
Sudah dandan, tapi makeup di sisi hidung malah cakey. Kesel banget kalau begini.
Coba pakai puff ini. Teksturnya lembut, jadi makeup di sisi hidung bisa nempel lebih rapi dan nggak gampang cakey. Aku juga suka karena puff ini nggak nyerap foundation.
Habis dipakai bisa dicuci, terus dipakai lagi buat makeup berikutnya. Lagi mau ganti puff? Ambil yang ini aja.
```

The raw input WAV/config and full prompt remain in the job; delivery uses a uniform -2.9dB voice gain plus existing quiet music and normal delivery-format encoding, without changing performance timing. See [Cushion Puff production state](../audit/cushion-puff-production-state.md) for exact final artifact and review binding. No further audio/video work is authorized by this profile.
