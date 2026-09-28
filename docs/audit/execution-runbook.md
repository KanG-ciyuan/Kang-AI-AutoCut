# Execution Runbook

How to run the production control path and its four execution boundaries **without any
prior conversation**. Everything needed is either in this repository or in the job's own
directory.

## Production bootstrap — a new real SKU starts here

Current job handoff: [Cushion Puff production state](cushion-puff-production-state.md).
This is a resume pointer for that job, not a default for another SKU.

This is the Agent's production reading and decision procedure, not a new runner or stage.
Start from this checkout and the current job; do not reconstruct missing instructions from
another SKU's conversation. The proof command in section 1 is an engineering demonstration,
not the intake command for a real product.

**Precedence and state.** Follow the current user scope and stop point, repository entry
rules, current job approvals and exact approved revisions, then the relevant contracts and
authoring guidance. Examples supply shapes, not SKU facts or approved parameters. Never
turn a contract PASS into human approval. Preserve uncommitted work and rejected versions;
record a superseding decision rather than rewriting their history. Conflicting approvals
or claims need explicit reconciliation before their dependent work proceeds.

Read `AGENTS.md`, `PROJECT_IDENTITY.md`, this bootstrap, the job Manifest/Handoff/latest
gate, and `docs/architecture/operations.md`. Check branch, HEAD and the working tree.
Resolve storage through the existing contract before writing frames or other working
media; initialize a new job through `job_foundation.initialize_production_job`. An existing
authoring folder is not proof that the production stages have been initialized or passed.

Then load the following in order as the job reaches each boundary:

Commercial intake order: **Product Understanding → Potential Selling Point Discovery →
Seller Confirmation → Seller-confirmed Product Facts → Commercial Strategy → Commercial
Copy**. Before strategy/copy, reconcile any existing seller answers and ask only the
remaining high-value questions. Pending material answers stop dependent authoring; an
explicit Seller Confirmation Gate stops all copy, including exploratory/raw speech.

| Decision | Required reading / action | Stop or output |
|---|---|---|
| Understand the product and material | `docs/policies/shot-intelligence.md`; actual sources and current fact/evidence boundaries | Separate observation, seller-confirmed information and inference; identify SKU conflicts and missing purchase reasons |
| Establish the commercial objective | Current brief; `docs/contracts/commercial-intelligence-v1.md` and `docs/contracts/commercial-strategy-v1.md` | Use the declared objective; the existing Intelligence default is DIRECT_CONVERSION only when unspecified, with its default provenance. Select attention/desire/trust/purchase-relevant information, not exhaustive description |
| Resolve unknown selling points | Seller Confirmation Before Commercial Copy in `docs/skills/commercial-copy-v1.md` | Discover SKU-specific opportunities, ask high-value questions and STOP at the seller gate; after answers, record their truth source, reconcile facts/claims and retain actual visual evidence status. Never turn internal unknowns into consumer verification instructions |
| Choose what to sell | Candidate strategy, available evidence and claim boundary | Human strategy/selling-point gate where requested; do not draft a selected strategy as if the user had approved it |
| Author creator speech | `docs/skills/commercial-copy-v1.md` in full, including Creator Speech Taste Reference; `docs/contracts/commercial-copy-v1.md` | Establish creator, audience relationship and speaking register; learn BAD/GOOD mechanisms, write with the picture, run the factual check AND the speech/sales review; obey the requested raw-speech or full-copy review scope |
| Localize | The same Skill's localization and back-check duties | Target-market speech plus faithful Chinese back-translation; explicit wording/use approval before TTS or words enter a video |
| Direct and generate voice | `docs/providers/audio-provider.md`; `docs/decisions/ADR-0006-continuous-voice-over.md` | Derive direction from this creator, market, product and approved copy; retain approved direction where valid; honor any prompt-review gate. Then one continuous performance and actual listening, never assumed duration |
| Plan audio and environment | `docs/policies/audio-intelligence.md` | Classify and listen to source windows; original advertising dialogue is not ambience. Creative audio review precedes mastering |
| Plan titles and spoken captions | `docs/policies/typography.md`; short-form input below | Titles and captions are separate; use exact approved words and measured FINAL-VO alignment, product/action reservations and phone-size review |
| Execute and assemble | `docs/policies/editing-intelligence.md`, execution boundaries below | Measured source PTS, job-declared geometry/audio/layout, actual artifact verification; do not invent missing producers |
| Review, repair and release | `docs/policies/reviewer-repair.md`; `docs/decisions/ADR-0008-targeted-repair.md` | Deterministic QA, independent review and human final gate stay distinct; repair the affected range and verify it; release binds the exact master |

Commercial Intelligence / Strategy / Copy remain **CONTRACT_ONLY / NOT_WIRED**. Their
creative decisions are Agent/human authored. Persona, seller questions and style review
live in existing job brief/review notes; they are not new schema fields, registered
producers or automatic services. Follow `docs/audit/production-chain-manifest.md` for
runtime readiness. If an external collaboration Skill is required for a delegated
takeover, resolve it under AGENTS rule 9; do not silently substitute another framework.

At any human stop, leave the job's current version, decision owner, unresolved questions,
approved scope and exact next allowed action in its handoff. A change to copy makes old
VO/caption bindings stale; approval of a voice *direction* does not authorize a prompt
that still embeds rejected words.

## 1. Reproduce the execution proof

```sh
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

This builds a small real job from local FFmpeg output, runs the normal control path, stops
at the human release gate, writes the release naming the verified master, resumes, and
then independently re-measures `final/master.mp4`. Exit code is `0` only when every
measurement passes.

## 2. Run the control path for a job

```sh
python3 -m src.ai_autocut.fast_path --job-root <JOB> [--stage <NAME>] [--no-resume]
```

`--stage` runs one semantic stage and checkpoints exactly like a full run. Without it the
run resumes at the first stage that has not passed. A completed stage is re-executed only
after `FastPath.invalidate(stage, reason=...)`, which also invalidates everything
downstream.

Exit codes: `0` PASS · `3` BLOCKED · `4` REVIEW_REQUIRED ·
`5` SUPERVISOR_DECISION_REQUIRED · `6` FAIL · `7` REJECT.

## 3. Run one execution boundary

```sh
python3 -m src.ai_autocut.execution_adapters --job-root <JOB> --boundary picture
python3 -m src.ai_autocut.execution_adapters --job-root <JOB> --boundary typography
python3 -m src.ai_autocut.execution_adapters --job-root <JOB> --boundary audio
python3 -m src.ai_autocut.execution_adapters --job-root <JOB> --boundary assemble
```

Each adapter reads this job's request and referenced job inputs. The original
commercial-title layout, font, geometry and audio targets remain job-declared.
The optional spoken-caption layer adds adaptive mobile layout defaults, with a
job-supplied bold font and safe-area overrides; it does not change title art direction.

### `picture` — `picture/picture_request.json`

```json
{"source": "<path>", "width": 1080, "height": 1920, "fps": 30,
 "units": [{"unit_id": "U01", "t_in_seconds": 0.0, "frames": 45,
            "geometry": {"mode": "FIT"}}]}
```

Writes `picture/picture_master.mp4`. If the fast path already extracted a unit to
`picture/ranges/<unit_id>.mp4`, that unit is reused rather than extracted twice, so there
is exactly one execution path.

**Per-unit geometry.** Each unit states its own geometry:

```json
{"unit_id": "U02", "t_in_seconds": 1.966667, "frames": 110,
 "geometry": {"mode": "CROP",
              "crop_rect": {"x": 135, "y": 0, "width": 810, "height": 1440},
              "confidence": "HIGH",
              "evidence_ref": "job/recon/framing_evidence.json"}}
```

- `FIT` scales preserving the aspect ratio and pads to `width`/`height`. It is the
  historical behaviour and remains the behaviour of a unit that declares **no** `geometry`
  at all, so every earlier request keeps working unchanged.
- `CROP` takes exactly the stated source rectangle and scales it to `width`/`height`.
  Nothing is padded, nothing is inferred and nothing is adjusted. `crop_rect` is required;
  it must be integer, lie inside the measured source frame, have an even width and height,
  and match the output aspect ratio. An invalid crop is **refused** — a `CROP` is never
  silently converted into a `FIT`.

`confidence` and `evidence_ref` are optional provenance for a geometry decision. This
executor **executes** a geometry decision; it never invents one, and it ships no
automatic framing of any kind.

Every unit's requested and applied geometry is recorded in the returned evidence and in
`picture/picture_finishing.json`.

### `typography` — `typography/typography_request.json`

```json
{"master": "picture/picture_master.mp4", "out": "typography/typography_master.mp4",
 "width": 540, "height": 960, "fps": 30, "frame_count": 90,
 "layout": {"baseline_y": 768, "left_margin": 48, "size_l1": 40, "size_l2": 32,
            "line_gap": 10, "fill": [255, 255, 255, 255]},
 "font_stack": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
 "events": [{"lines": ["HELLO"], "start_frame": 0, "end_frame_exclusive": 45}]}
```

`layout` and `font_stack` are **required**. Writes the composited picture to `out`.

### `audio` — `audio/audio_request.json`

```json
{"assets": [{"path": "assets/voice.wav", "gain_db": 0.0, "start_seconds": 0.0}],
 "out": "audio/audio_master.wav", "duration_seconds": 3.0,
 "target_lufs": -16.0, "true_peak_ceiling_dbtp": -1.5}
```

Mixes this job's local assets with FFmpeg and measures the result. Makes no provider
call. A mix whose sample peak reaches full scale is refused rather than reported.

### `assemble` — `assemble/assemble_request.json`

```json
{"picture": "typography/typography_master.mp4", "audio": "audio/audio_master.wav",
 "out": "final/master.mp4", "method": "REMUX"}
```

`REMUX` is preferred when the inputs already meet the delivery specification. Writes the
master plus measured evidence to `assemble/assembly_evidence.json`.

## 4. What verification actually does

`verify_assembly_evidence` opens the file. It refuses, in order:

1. a missing or unreadable master;
2. a supplied `master_sha256` that does not match the recomputed digest;
3. a supplied `frame_count` that does not match the decoded count;
4. a decoded count that disagrees with the upstream evidence this run produced;
5. any black frame;
6. a freeze — three or more consecutive identical decoded frames;
7. a master with no audio stream, or unmeasurable loudness;
8. clipping, or a true peak above the job's ceiling;
9. a supplied loudness that disagrees with the measurement by more than 0.5 LU.

A JSON claim is never sufficient. `tests/test_real_master_proof.py` asserts that deleting
the master, or re-encoding it in place, makes verification fail.

## 5. The human release

`release/human_release.json` is a **separate act from the review**, and must name the
master it approves:

```json
{"schema_version": "human_release.v1", "decision": "APPROVED", "authority": "<name>",
 "review_verdict": "PRODUCTION_READY", "master_sha256": "<64 hex>",
 "statement": "<what was reviewed>"}
```

`PRODUCTION_READY` from a reviewer produces `SUPERVISOR_DECISION_REQUIRED`, never a
release. A release naming a different master, or answering a different verdict, is
refused.

## 6. The timebase invariant

```
SOURCE        = measured PTS timestamp
ANALYSIS GRID = decoded indices resolved from that PTS, plus the CFR count
TIMELINE      = CFR frame grid
```

Placement coordinates are **derived** from the measured timestamp, not validated and then
ignored. `local_preview.execute_local_preview` requires an explicit `production_scope`
and refuses `THIRD_SKU_PRODUCTION`, because it selects source frames by decoded index.

## 7. The intervention ledger

Written automatically to `intervention_ledger.jsonl` when a gate halts a run. The actor is
taken from the producer that must act (`CODEX_SUPERVISOR`, `HUMAN`, `AUTOMATED_REPAIR`).
A still-open gate is recorded once. A resolved gate, a `REJECT`, a paid call and a
successful human release are recorded when they occur. The operator is not asked to
remember any of it.

## Short-form spoken-caption input

After approval, prepare the final VO using the existing
[Voice Direction guidance](../providers/audio-provider.md#reusable-voice-direction--production-guidance).
Align words **after** all permitted silence/timing repairs. Read
[environment selection rules](../policies/audio-intelligence.md#environment--evidence-audio--production-rules-after-v2)
when preparing the Audio Program. Neither guidance introduces a new agent.

Add this optional member to the existing `typography/typography_request.json`:

```json
{
  "spoken_captions": {
    "approved_copy": "copy/spoken.txt",
    "alignment": "copy/final-vo-words.json",
    "phrase_ends": [2, 5],
    "safe_area": [0.08, 0.08, 0.16, 0.16],
    "reserved_regions": []
  }
}
```

This is a member example, not a complete typography request. Retain existing
picture, canvas, frame rate/count, output, title events, bold font stack and either
layout or Art Direction profile. `phrase_ends`, `safe_area`, and `reserved_regions`
are optional. The indices in this example assume a five-word approved copy.
Regions are pixel `[left, top, right, bottom]` rectangles; supply product/action
and platform obstructions from current picture evidence. Titles are reserved by
the renderer automatically. Flat requests may use an empty title-events array
when captions alone are needed, but retain the existing layout declaration.

The alignment file contains:

```json
{
  "copy_sha256": "<SHA-256 of approved UTF-8 copy file bytes>",
  "audio_path": "audio/final-vo.wav",
  "audio_sha256": "<SHA-256 of final VO file bytes>",
  "timing_source": "forced_alignment",
  "words": [{"text": "<approved word>", "start": 0.12, "end": 0.39}]
}
```

Provide every word, in order, once. The sample is illustrative, not executable.
Allowed timing sources: `forced_alignment`, `asr_reviewed`, `manual_measured`.
All times are measured seconds on the final audio/master timeline, not average
word-duration estimates. Negative, overlapping, reversed or out-of-duration
intervals are refused, as are stale text/audio hashes. ASR should be reviewed
against the actual performance before being labelled `asr_reviewed`.

Run the existing **PLAN THE WORDS / typography** boundary after the final VO and
alignment exist. On a resumed job invalidate PLAN THE WORDS and downstream
checkpoints using the existing control path; do not regenerate approved copy,
picture or provider audio. If a job normally plans titles before VO exists, that
first pass remains title-only; caption execution requires the later final-VO input.
No stage ordering or Producer Registry was changed to hide this dependency.

`typography_execution.json` includes `spoken_captions` evidence: copy/audio hashes,
alignment source, exact phrase words/lines, actual time windows, safe rectangle,
font size, state count and whether grouping was producer-supplied or heuristic.
The existing title result fields remain unchanged. Rendering produces stable PNG
states and composites them with titles in one encode. Caption temporary media stays under the resolved job typography directory
and is removed after rendering; resolve the job on approved production storage. This
minimal implementation is intended for short clips; it is not a long-form subtitle
streaming engine. Review source text, synchronization, product clearance and final
legibility through the existing review gates; deterministic tests do not certify
subjective commercial quality.
