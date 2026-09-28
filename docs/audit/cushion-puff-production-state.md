# Cushion Puff Production — current handoff

Updated 2026-09-28. **Job-specific state; Human PASS is bound to the exact final artifact, not a new general production rule.**

## Resume without chat history

Read AGENTS.md, PROJECT_IDENTITY.md and execution-runbook.md Production bootstrap. Resolve the existing job with the configured local environment:

```sh
scripts/with-local-env python3 -m src.ai_autocut.storage_contract --job-id cushion-puff-id-coldstart-20260926 --print-workspace
```

Then read `handoff.md` and `current-production-state.json` inside that resolved workspace. Paths below are relative to the job. Exit 3 means storage blocked; do not fall back to internal storage. No new paid generation or production is authorized. The 2026-09-28 Git provenance audit resolved the former historical Commercial hold; see [Closeout scope](cushion-puff-closeout-scope.md).

## Current decision and deliverable — HUMAN PASS

Human selected **dry VO v4 Take 1 (23.78s)** and authorized a **24-second finished video** retaining the accepted elements, then asked for a durable handoff. Human-approved production result:

`preview/take1-24s-finished-v1/Cushion-Puff-Indonesia-Take1-24s-Finished-v1.mp4`

1080×1920, 30fps, 720 frames; 10 source files / 12 edited segments; 3 retained titles, current-copy spoken captions with active-word highlighting, retained background music. No new provider calls. Voice stays at native speed; no stretch, pause cuts or sentence splicing. Final mix -18.02 LUFS / -3.69 dBTP. Technical decode/geometry/black/freeze/hash checks and rendered sampled-frame review completed. **Human Final Review: PASS / 满意.** Human approved the exact final result; no reliable Agent listening or independent creative review is retroactively asserted. This job-authored render is not a claim that all formal Fast Path gates passed.

The Human-reported single knock-like sound remains in Take 1. Takes 2/3 were rejected for excessive laughter. Do not label output noise-free or regenerate to repair without new authorization. The old 32.9s Finished-B-v1, old opening “Sebelah hidung sini, nih” and earlier auditions are historical, not the current inputs.

## Authoritative current inputs

| Role | Job-relative file |
|---|---|
| Seller facts | `brief/product_facts.v3.json` |
| Visual boundary | `evidence/visual_evidence_boundary.json` |
| Strategy | `strategy/commercial_strategy.formal-v4.json` |
| Exact approved copy | `strategy/commercial_copy.human-v4-dry.json` |
| Copy approval | `approvals/copy-v4-dry-vo-approval.json` |
| Selected raw voice | `audio/cushion-puff-dry-vo-v4/takes/VO-Take-1.wav` |
| Actual complete generation prompt | `audio/cushion-puff-dry-vo-v4/exact-scene-prompt.txt` |
| Actual generation parameters | `audio/cushion-puff-dry-vo-v4/technical/config.json` |
| Take selection | `audio/cushion-puff-dry-vo-v4/human-review-selection.json` |
| Latest 24s authorization | `approvals/take1-24s-finish-approval.json` |
| Current render provenance and checks | `preview/take1-24s-finished-v1/production-record.json` and `qc/checks.json` |
| Reproduction and exact source ranges | Same folder: `reproduce/`, `timeline.json`, `shot-breakdown.md` |
| Integrity / full current state | Same folder: `integrity.json`; job root: `current-production-state.json` |

Raw selected VO SHA-256: `25d915c874e225fc9d7a4a51a3fdd1ad5ff80b514deed96d3683fa6860912434`.

## Voice identity and prompt decisions

Domestic **seed-audio-1.0**, official **speech_rate=0** (Human-selected Rate A), pitch_rate=0, loudness_rate=0, WAV 40000Hz stereo, enable_subtitle=false. Fixed original 19.88s reference binds via `references[0].audio_data` and `@音频1`; no persistent speaker ID. Original reference: `audio/voice-reference-transfer-v1/reference/Indonesia-Beauty-Creator-Voice-Reference-v1-Candidate.wav`, SHA-256 `a63f8fb9f136fcb5a7dc1a8e5a90569ea2aa3816f661caf7d2fe16171c3b41cb`.

Human approved identity and Rate A in separate tests. Keep the original reference: neither blind B output nor selected Take 1 replaces it. The working Voice Profile has been updated to record the accepted dry segmented production example; its prior version is preserved in the job closeout archive. Actual config/prompt files above remain the authority for reproducing this take family. The current prompt still contains strong smiling/enthusiastic scene descriptions; those were not redesigned. They may contribute to laughter but causality is unproven. Do not invent a prompt-quality conclusion from the A/B history.

Default discussed production policy is three identical-config takes followed by Human selection. That stage is complete for this candidate; **do not generate more**. Source voice remains raw; delivery gain/music do not redefine the voice reference.

## Boundaries and next step

Seller-confirmed facts can be spoken even when footage only supports the use context. Nose fit / non-absorption are not visually proven experiments. Rinse footage proves washing actions, not antibacterial, instant-clean, quick-dry or lifetime claims. Pack quantity stays unknown and out of consumer copy.

Production is **complete and Human PASS**. Stop optimization, new VO, recutting and Prompt/TTS research. Do not repeat approved voice selection, rate tests, claims or copy decisions. The older Commercial contract provenance was recovered and audited on 2026-09-28; it remains contract-only. Full audit: [Closeout scope](cushion-puff-closeout-scope.md). No artifacts were deleted or moved. Prune production intermediates only under the normal artifact lifecycle policy, not as part of this Git audit.

## Final lock and resumption

Final video SHA-256: `f2f0568887cac996e5563b7f955cd85a341c956acaa4189590345259fe6d32d4`.

- Exact final video/VO/reference absolute paths, model, request parameters, actual prompt, approved full copy and complete source usage: job `closeout/final-production-lock.json`.
- Explicit Human PASS bound to video hash: `approvals/human-final-review-pass.json`.
- Current state/handoff: job `current-production-state.json` and `handoff.md`.
- Final integrity record: `preview/take1-24s-finished-v1/integrity.json`; preserved pre-PASS records: `closeout/before-human-pass/`.
- Reusable identity/rate, actual prompt and copy, take policy, listening-QC priority, practice versus hypothesis: [Indonesia Beauty Creator Voice v1](../providers/indonesia-beauty-creator-voice-v1.md).

The engineering baseline remains **Phase 3 Hook Planning**; **Phase 4 has not started**. Cushion Puff is a Human-validated real production result using job-authored decisions and existing execution components. This does not convert Commercial contract-only modules to wired generators or certify an unattended end-to-end Fast Path. Check Git history and remote `main` for the exact closeout SHA rather than relying on the pre-audit baseline SHA above.

Next session: read this state and the job handoff first, then start from a new brief if requested. A new SKU starts with its own materials, seller facts and approvals. Reuse validated voice identity/rate when appropriate; do not reopen this finished SKU by default.
