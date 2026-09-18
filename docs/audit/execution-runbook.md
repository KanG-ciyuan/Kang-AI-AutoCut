# Execution Runbook

How to run the production control path and its four execution boundaries **without any
prior conversation**. Everything needed is either in this repository or in the job's own
directory.

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

Each adapter reads this job's own request file and nothing else. None of them ships a
default layout, font, geometry, loudness target or true-peak ceiling: a job that does not
state its own values cannot be executed. That is deliberate — a default here would be one
job's art direction applied to another.

### `picture` — `picture/picture_request.json`

```json
{"source": "<path>", "width": 540, "height": 960, "fps": 30,
 "units": [{"unit_id": "U01", "t_in_seconds": 0.0, "frames": 45}]}
```

Writes `picture/picture_master.mp4`. If the fast path already extracted a unit to
`picture/ranges/<unit_id>.mp4`, that unit is reused rather than extracted twice, so there
is exactly one execution path.

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
